# SQLITE rules

Detailed entries for `SQLITE-001..SQLITE-015`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

The rules describe one design: one process with many threads, WAL, one
writer connection behind a lock, and a pool of read-only snapshot readers,
driven from Python's `sqlite3` module (3.12+ for `autocommit=`). Quotes are
verbatim from the SQLite 3.53.1 and Python 3.14 docs.

---

## SQLITE-001 — Set journal_mode=WAL on the writer and check the mode it returns

**What.** The writer runs `PRAGMA journal_mode = WAL` once at open, reads
the row it returns, and refuses to start unless it is `'wal'`. Readers
don't set it; WAL is a property of the database file.

**Why.** WAL lets readers and the writer run at the same time, which the
rest of this design depends on. The pragma doesn't raise when it can't
switch modes: it returns the mode that is actually in effect. Code that
ignores the result keeps running in rollback-journal mode, where the
writer and readers block each other, and nothing reports it.

Source: <https://sqlite.org/pragma.html#pragma_journal_mode>

> The new journal mode is returned. If the journal mode could not be changed, the original journal mode is returned.
> — SQLite 3.53.1 docs

> The WAL journaling mode is persistent; after being set it stays in effect across multiple database connections and after closing and reopening the database.
> — SQLite 3.53.1 docs

**How.**

```python
import sqlite3

writer = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
mode = writer.execute("PRAGMA journal_mode = WAL").fetchone()[0]
if mode != "wal":
    writer.close()
    raise RuntimeError(f"journal_mode is {mode!r}, not 'wal'")
```

**When NOT to apply.** Databases that must work over a network
filesystem, or be opened by processes on more than one host, can't use
WAL (see SQLITE-014). An in-memory database never reports `wal`, so this
check rejects it; tests use a temporary file instead.

---

## SQLITE-002 — synchronous=NORMAL with WAL: never corrupt, but the last commits can be lost on power loss

**What.** Every connection runs `PRAGMA synchronous = NORMAL`. The setting
is per connection and isn't stored in the file.

**Why.** In WAL mode, NORMAL skips the fsync of the WAL at every commit
and syncs only around checkpoints. That is the difference between 619 and
18,173 commits per second in a commit-per-row benchmark (SQLite 3.53.1,
local disk; see SQLITE-013). The trade-off is exact: the database stays
consistent, and an application crash loses nothing, but a power loss or
OS crash can roll back transactions that had already committed.

Source: <https://sqlite.org/pragma.html#pragma_synchronous>

> WAL mode is always consistent with synchronous=NORMAL, but WAL mode does lose durability. A transaction committed in WAL mode with synchronous=NORMAL might roll back following a power loss or system crash. Transactions are durable across application crashes regardless of the synchronous setting or journal mode.
> — SQLite 3.53.1 docs

**How.** Keep every per-connection pragma in one tuple and run it on each
new connection (SQLITE-004 and SQLITE-012 add to the same list):

```python
import sqlite3

# None of these persist in the database file, so every connection sets them.
CONNECTION_PRAGMAS = (
    "PRAGMA foreign_keys = ON",  # off by default, for backward compatibility
    "PRAGMA synchronous = NORMAL",  # safe with WAL: a power loss can drop the last commits, never corrupt
    "PRAGMA cache_size = -65536",  # 64 MiB page cache (negative means KiB)
    "PRAGMA temp_store = MEMORY",  # temp tables and indices (sorts, GROUP BY) stay off disk
)


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, autocommit=True, timeout=5.0)
    for pragma in CONNECTION_PRAGMAS:
        conn.execute(pragma)
    return conn


conn = connect("app.db")
```

**When NOT to apply.** When a committed transaction must survive a power
loss (a payment someone has been told succeeded, an acknowledged
message), use `synchronous = FULL`. With a rollback journal, NORMAL
carries a small risk of corruption; this pairing only applies to WAL.

---

## SQLITE-003 — Give every connection a busy timeout (in Python: `connect(timeout=)`)

**What.** Every connection is opened with
`sqlite3.connect(..., timeout=5.0)`. Python installs that as SQLite's
busy handler, so a connection that finds the database locked retries for
up to 5 s before raising `OperationalError` (`SQLITE_BUSY`).

**Why.** Without a busy handler, SQLite returns `SQLITE_BUSY` the moment
another connection holds the lock it needs. With in-process writers
already queued on a Python lock (SQLITE-006), that's another process
holding the write lock. In Python the `timeout` argument *is* the busy
timeout (`PRAGMA busy_timeout` reads 5000 afterwards), so a separate
PRAGMA would only restate it. 5.0 is also the default, but pass it
explicitly because the value is a decision. Other drivers and the C API
install no handler by default.

Sources: <https://sqlite.org/c3ref/busy_timeout.html>,
<https://docs.python.org/3.14/library/sqlite3.html#sqlite3.connect>

> This routine sets a busy handler that sleeps for a specified amount of time when a table is locked. The handler will sleep multiple times until at least "ms" milliseconds of sleeping have accumulated. After at least "ms" milliseconds of sleeping, the handler returns 0 which causes sqlite3_step() to return SQLITE_BUSY.
> — SQLite 3.53.1 docs

> How many seconds the connection should wait before raising an "OperationalError" when a table is locked.
> — Python 3.14 docs

**How.**

```python
import sqlite3

# timeout= is the busy timeout: wait up to 5 s for a lock instead of failing at once.
conn = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
assert conn.execute("PRAGMA busy_timeout").fetchone()[0] == 5000
```

**When NOT to apply.** It only helps with waits that can end. A deferred
transaction whose snapshot has gone stale fails at once with
`SQLITE_BUSY_SNAPSHOT`, whatever the timeout (see SQLITE-005).
Latency-critical paths may want a shorter timeout and to handle the error
themselves.

---

## SQLITE-004 — Turn foreign_keys on for every connection; it's off by default

**What.** Every connection runs `PRAGMA foreign_keys = ON` right after
connecting, before any transaction starts, so an insert that references a
missing row is rejected.

**Why.** SQLite parses `REFERENCES` clauses but doesn't enforce them
unless the connection enables enforcement. A connection that skips the
pragma writes orphan rows without any error. The setting isn't stored in
the file, and the pragma does nothing inside an open transaction, so the
place to set it is the connect path.

Source: <https://sqlite.org/foreignkeys.html>

> Foreign key constraints are disabled by default (for backwards compatibility), so must be enabled separately for each database connection.
> — SQLite 3.53.1 docs

**How.**

```python
import sqlite3

conn = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
conn.execute("PRAGMA foreign_keys = ON")  # in the connect path, before any BEGIN
conn.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY) STRICT")
conn.execute(
    "CREATE TABLE IF NOT EXISTS transfer ("
    " id INTEGER PRIMARY KEY, source INTEGER NOT NULL REFERENCES account (id)) STRICT"
)
try:
    conn.execute("INSERT INTO transfer (source) VALUES (?)", (999,))
except sqlite3.IntegrityError:
    pass  # FOREIGN KEY constraint failed, as intended
```

**When NOT to apply.** A migration that rebuilds a table (the 12-step
`ALTER TABLE` procedure) needs enforcement off while it runs. It has to
turn it off outside the transaction, and then run
`PRAGMA foreign_key_check` before turning it back on.

---

## SQLITE-005 — Start write transactions with BEGIN IMMEDIATE, and roll back a failed COMMIT only if a transaction is still open

**What.** The write path runs `BEGIN IMMEDIATE`, yields the connection,
then runs `COMMIT`. In a `finally`, it runs `ROLLBACK` only if
`conn.in_transaction` is still true. That covers the block raising, and
it covers `COMMIT` itself failing.

**Why.** A plain `BEGIN` is deferred: the transaction starts as a read,
and only takes the write lock at its first write. In WAL mode, if another
connection commits in between, that upgrade fails with
`SQLITE_BUSY_SNAPSHOT`, in the middle of the transaction. Waiting can't
fix it, because the snapshot is stale and the whole transaction has to
restart. `BEGIN IMMEDIATE` takes the write lock up front, so the only
place it waits is `BEGIN`, which is where `busy_timeout` handles it.
Nothing after that returns `SQLITE_BUSY`. A failed `COMMIT` (a deferred
foreign-key violation, or `SQLITE_BUSY`) can leave the transaction open,
and a connection returned in that state breaks the next `BEGIN`. After
errors such as `SQLITE_FULL` or `SQLITE_IOERR`, SQLite may already have
rolled back, and an unconditional `ROLLBACK` would then raise and hide
the original error
(<https://sqlite.org/lang_transaction.html#response_to_errors_within_a_transaction>).

Source: <https://sqlite.org/isolation.html>

> The attempt by X to escalate its transaction from a read transaction to a write transaction fails with an SQLITE_BUSY_SNAPSHOT error because the snapshot of the database being viewed by X is no longer the latest version of the database.
> — SQLite 3.53.1 docs

> If the BEGIN IMMEDIATE operation succeeds, then no subsequent operations in that transaction will ever fail with an SQLITE_BUSY error.
> — SQLite 3.53.1 docs

**How.**

```python
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager

writer = sqlite3.connect(
    "app.db", autocommit=True, check_same_thread=False, timeout=5.0
)
write_lock = threading.Lock()


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    """A write transaction: commits when the block ends, rolls back if the block or COMMIT raises."""
    with write_lock:
        writer.execute("BEGIN IMMEDIATE")
        try:
            yield writer
            writer.execute("COMMIT")
        finally:
            # A failed COMMIT leaves the transaction open; after some errors (SQLITE_FULL, IOERR)
            # SQLite has already rolled back, and a second ROLLBACK would mask the real error.
            if writer.in_transaction:
                writer.execute("ROLLBACK")


with write() as conn:
    conn.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT) STRICT")
```

**When NOT to apply.** Read-only work shouldn't use it, because it takes
the single write lock (SQLITE-006 covers reads). `BEGIN EXCLUSIVE` gains
nothing over `IMMEDIATE` in WAL mode.

---

## SQLITE-006 — One writer connection and a pool of read-only (mode=ro) readers, each read in one explicit transaction

**What.** Open one read-write connection, serialized by a
`threading.Lock`, and a fixed pool of connections opened with the URI
parameter `mode=ro`, handed out through a `queue.SimpleQueue`. The read
path wraps its block in `BEGIN … ROLLBACK`, so every statement in the
block reads from one snapshot, pinned at the block's first read.

**Why.** SQLite allows one writer at a time, so a single writer
connection behind a lock matches the engine and keeps in-process writers
from contending for the file lock. In WAL mode, readers on their own
connections never wait for the writer. With an explicit transaction, a
multi-statement read (a balance, then that account's transfers) can't see
half of a concurrent write. `mode=ro` makes a stray write fail with
"readonly" instead of running.

Source: <https://sqlite.org/isolation.html>

> WAL mode permits simultaneous readers and writers.
> — SQLite 3.53.1 docs

> When a read transaction starts, that reader continues to see an unchanging "snapshot" of the database file as it existed at the moment in time when the read transaction started. Any write transactions that commit while the read transaction is active are still invisible to the read transaction
> — SQLite 3.53.1 docs

**How.**

```python
import queue
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    uri = f"{path.resolve().as_uri()}?mode={'ro' if read_only else 'rwc'}"
    return sqlite3.connect(
        uri, uri=True, autocommit=True, check_same_thread=False, timeout=5.0
    )


path = Path("app.db")
writer = connect(path, read_only=False)  # guarded by a threading.Lock (SQLITE-005)
writer.execute("PRAGMA journal_mode = WAL")
readers: queue.SimpleQueue[sqlite3.Connection] = queue.SimpleQueue()
for _ in range(4):
    readers.put(connect(path, read_only=True))


@contextmanager
def read() -> Iterator[sqlite3.Connection]:
    """A read transaction on a pooled read-only connection (blocks if all are in use)."""
    conn = readers.get()
    try:
        conn.execute("BEGIN")
        try:
            yield conn
        finally:
            if conn.in_transaction:  # a read has nothing to commit; never pool an open transaction
                conn.execute("ROLLBACK")
    finally:
        readers.put(conn)


with read() as conn:
    tables = conn.execute("SELECT count(*) FROM sqlite_schema").fetchone()[0]
```

**When NOT to apply.** Keep read blocks short. An open read transaction
stops a checkpoint from resetting the WAL, so a reader that holds one
indefinitely lets the `-wal` file grow. A block that reads and then
decides to write must use the write path for the whole thing
(SQLITE-005), not a read followed by a write. Several processes each get
their own writer connection. They then serialize on the file lock through
`busy_timeout`, not on the Python lock.

---

## SQLITE-007 — `PRAGMA optimize = 0x10002` at open (after migrations), periodically, and at close

**What.** Once migrations have run, the writer runs
`PRAGMA optimize = 0x10002`. A periodic `optimize()` call, which the
application schedules (hourly or daily) and which `close()` also calls,
runs the same mask.

**Why.** Query-planner statistics (`sqlite_stat1`) go stale as tables
grow, and a planner with stale or missing statistics can pick the wrong
index. `optimize` runs `ANALYZE` only on tables that look like they'd
benefit (bit `0x00002`). Bit `0x10000` makes it check every table, not
only the ones this connection's own queries have used. That matters
twice in this design: a freshly opened connection has used none, and
every query runs on the read-only reader connections, which can't
`ANALYZE`. So the writer, the only connection that can, has to look at
all tables every time. Running it after migrating also covers the
documented "after a schema change" case (a migration that creates
indexes). The `0x10000` bit was added in SQLite 3.46.0, so guard it with
a minimum-version check on `sqlite3.sqlite_version_info`.

Source: <https://sqlite.org/pragma.html#pragma_optimize>

> Applications that use long-lived database connections should run "PRAGMA optimize=0x10002;" when the connection is first opened, and then also run "PRAGMA optimize;" periodically, perhaps once per day or once per hour.
> — SQLite 3.53.1 docs

> All applications should run "PRAGMA optimize;" after a schema change, especially after one or more CREATE INDEX statements.
> — SQLite 3.53.1 docs

**How.**

```python
import sqlite3

# Python bundles its own SQLite: check the library actually loaded, not the OS's.
MIN_SQLITE = (3, 46, 0)
if sqlite3.sqlite_version_info < MIN_SQLITE:
    raise RuntimeError(f"SQLite {sqlite3.sqlite_version} is older than {MIN_SQLITE}")

writer = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
# ... run migrations (SQLITE-008) ...
writer.execute("PRAGMA optimize = 0x10002")  # at open; call again on a schedule and at close
```

**When NOT to apply.** Note that `0x10002` doesn't include `0x00010`, the
bit that caps `ANALYZE` with a temporary analysis limit. On very large
tables, add that bit (`0x10012`) or schedule the call off the hot path.
The pragma does nothing useful for a database without indexes.

---

## SQLITE-008 — Migrations keyed on PRAGMA user_version: each step and its version bump in one BEGIN IMMEDIATE transaction, the version re-read under the lock

**What.** Migrations are an ordered list, and each step is a list of SQL
statements. The migrate loop opens a write (`BEGIN IMMEDIATE`)
transaction on each pass and reads `PRAGMA user_version`. If the version
is below the number of steps, it runs step `version` and sets
`user_version = version + 1`, then commits. It stops when the version
equals the number of steps, and refuses to open a database whose version
is higher, meaning a schema newer than the code.

**Why.** SQLite DDL is transactional, and the `user_version` header field
is written in the same transaction (setting it and rolling back leaves it
unchanged, checked against SQLite 3.53.1). So a step either lands with
its version bump or not at all. Reading the version after
`BEGIN IMMEDIATE` has taken the write lock means two processes opening a
fresh file at once can't both apply the same step. `user_version` is
reserved for the application, so it needs no bookkeeping table.

Source: <https://sqlite.org/pragma.html#pragma_user_version>

> The user-version is an integer that is available to applications to use however they want. SQLite makes no use of the user-version itself.
> — SQLite 3.53.1 docs

From <https://sqlite.org/pragma.html#pragma_foreign_keys>, which is why migrations that change
foreign keys toggle enforcement outside the transaction:

> This pragma is a no-op within a transaction; foreign key constraint enforcement may only be enabled or disabled when there is no pending BEGIN or SAVEPOINT.
> — SQLite 3.53.1 docs

**How.** `write()` is the `BEGIN IMMEDIATE` context manager from
SQLITE-005:

```python
import sqlite3
from collections.abc import Iterator, Sequence
from contextlib import contextmanager

writer = sqlite3.connect("app.db", autocommit=True, timeout=5.0)


@contextmanager
def write() -> Iterator[sqlite3.Connection]:
    writer.execute("BEGIN IMMEDIATE")
    try:
        yield writer
        writer.execute("COMMIT")
    finally:
        if writer.in_transaction:
            writer.execute("ROLLBACK")


MIGRATIONS: list[Sequence[str]] = [
    ["CREATE TABLE account (id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE) STRICT"],
    ["CREATE INDEX account_name ON account (name)"],
]


def migrate(migrations: Sequence[Sequence[str]]) -> None:
    while True:
        with write() as conn:
            version: int = conn.execute("PRAGMA user_version").fetchone()[0]
            if version > len(migrations):
                raise RuntimeError(f"database is at schema {version}, newer than this code")
            if version == len(migrations):
                return
            for statement in migrations[version]:
                conn.execute(statement)
            # PRAGMA takes no bound parameters; the value is an int computed here, not input.
            conn.execute(f"PRAGMA user_version = {version + 1:d}")


migrate(MIGRATIONS)
```

**When NOT to apply.** A step that has to change `foreign_keys` (a table
rebuild) can't do it here, because that pragma does nothing inside a
transaction. Such a step needs its own path outside the write
transaction. Something that already owns the `user_version` field
(another tool or library) needs a migrations table instead. Steps have to
be SQL only; data migrations that need application code need a hook this
design doesn't have.

---

## SQLITE-009 — Pass every value as a bound parameter

**What.** Every value reaches SQL through a `?` placeholder and a
parameter tuple, never through string formatting. A name such as
`x'); DROP TABLE account; --` is stored as data.

**Why.** Values formatted into SQL text can change the statement's
meaning (SQL injection), and quoting them by hand gets the escaping
wrong. Bound parameters are passed as values that can never be parsed as
SQL, and statements with identical text reuse the driver's
prepared-statement cache.

Source: <https://docs.python.org/3.14/library/sqlite3.html#sqlite3-placeholders>

> Always use placeholders instead of string formatting to bind Python values to SQL statements, to avoid SQL injection attacks
> — Python 3.14 docs

**How.**

```python
import sqlite3

conn = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
conn.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY, name TEXT NOT NULL, balance INTEGER NOT NULL) STRICT")
name, balance = "x'); DROP TABLE account; --", 100
account_id = conn.execute(
    "INSERT INTO account (name, balance) VALUES (?, ?) RETURNING id",
    (name, balance),
).fetchone()[0]
```

**When NOT to apply.** Only values can be bound. Identifiers and `PRAGMA`
arguments can't: `PRAGMA user_version = ?` is a syntax error. Format such
a value only when the code computed it, the way SQLITE-008 formats
`f"PRAGMA user_version = {version + 1:d}"` with `:d` so it can only
produce digits. Any other identifier that has to be spliced in must come
from a fixed allow-list in the code.

---

## SQLITE-010 — STRICT tables, CHECK constraints, and money as integer cents

**What.** Every table is `STRICT`, and every column has a declared type.
Money is an `INTEGER` count of cents. `CHECK (balance >= 0)` and
`CHECK (amount > 0)` encode the invariants in the schema.

**Why.** An ordinary SQLite column stores a value of the wrong type if it
can't convert it (`'a lot'` in an `INTEGER` column is kept as text). A
`STRICT` table raises instead. It still converts losslessly, so `'123'`
becomes `123`. A `REAL` is an IEEE double, which can't represent 0.10
exactly, so money kept as floats drifts; integer cents add up exactly.
`CHECK` constraints catch a buggy code path that tries to break an
invariant, even when that path bypasses the application's own
validation.

Source: <https://sqlite.org/stricttables.html>

> If the value cannot be losslessly converted in the specified datatype, then an SQLITE_CONSTRAINT_DATATYPE error is raised.
> — SQLite 3.53.1 docs

> CHECK constraints work the same.
> — SQLite 3.53.1 docs

**How.**

```python
import sqlite3

conn = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
conn.execute(
    """CREATE TABLE IF NOT EXISTS account (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL UNIQUE,
        balance INTEGER NOT NULL CHECK (balance >= 0)
    ) STRICT"""
)
conn.execute(
    """CREATE TABLE IF NOT EXISTS transfer (
        id INTEGER PRIMARY KEY,
        source INTEGER NOT NULL REFERENCES account (id),
        target INTEGER NOT NULL REFERENCES account (id),
        amount INTEGER NOT NULL CHECK (amount > 0)
    ) STRICT"""
)
```

**When NOT to apply.** A `STRICT` table can only be read or written by
SQLite 3.37.0 or later. Columns that are meant to hold values of mixed
types should use `ANY`, not a non-strict table. `CHECK` runs only on
writes, and `PRAGMA ignore_check_constraints` can turn it off, so it adds
a guard; it doesn't replace validation at the boundary.

---

## SQLITE-011 — Python sqlite3 with autocommit=True (3.12+) and check_same_thread=False, one thread per connection at a time

**What.** Open connections with
`sqlite3.connect(uri, uri=True, autocommit=True, check_same_thread=False)`.
Every transaction is an explicit `BEGIN IMMEDIATE`/`BEGIN` …
`COMMIT`/`ROLLBACK` (SQLITE-005, SQLITE-006). A lock (the writer) or a
queue (the readers) makes sure only one thread uses a connection at a
time.

**Why.** The Python docs recommend `autocommit=False`, but in that mode
`sqlite3` keeps a transaction open at all times and opens it with
`BEGIN DEFERRED`. That would give the writer deferred transactions
(SQLITE-005's `SQLITE_BUSY_SNAPSHOT`), and give every idle pooled reader
a permanently open read transaction, which pins a stale snapshot and
holds up WAL checkpoints. `autocommit=True` gives control to SQLite's own
autocommit mode, so the code decides where each transaction starts. The
pre-3.12 default (`LEGACY_TRANSACTION_CONTROL`) opens transactions
implicitly before some statements, and the code shouldn't have to know
which. `check_same_thread=False` is needed because a pooled connection is
created on one thread and used on others. It's safe because the pool, not
the driver, guarantees one user at a time.

Source: <https://docs.python.org/3.14/library/sqlite3.html#sqlite3-transaction-control-autocommit>

> "sqlite3" ensures that a transaction is always open, so "connect()", "Connection.commit()", and "Connection.rollback()" will implicitly open a new transaction (immediately after closing the pending one, for the latter two). "sqlite3" uses "BEGIN DEFERRED" statements when opening transactions.
> — Python 3.14 docs

> If "False", the connection may be accessed in multiple threads; write operations may need to be serialized by the user to avoid data corruption.
> — Python 3.14 docs

**How.**

```python
import sqlite3
from pathlib import Path

uri = f"{Path('app.db').resolve().as_uri()}?mode=rwc"
conn = sqlite3.connect(
    uri, uri=True, autocommit=True, check_same_thread=False, timeout=5.0
)
assert not conn.in_transaction  # nothing opens a transaction until the code runs BEGIN
```

**When NOT to apply.** A single-threaded script with one connection can
keep the default `check_same_thread=True`, and `autocommit=False` with
`commit()` is fine for simple code with only one writer. Don't share one
connection between threads that use it at the same time:
`check_same_thread=False` removes the check, not the need for
serialization.

---

## SQLITE-012 — cache_size (negative means KiB) and temp_store=MEMORY on every connection

**What.** Every connection runs `PRAGMA cache_size = -65536`, a 64 MiB
page cache instead of the default of about 2 MB (`-2000`), and
`PRAGMA temp_store = MEMORY`.

**Why.** A negative `cache_size` sets a memory budget in KiB, independent
of page size; a positive value counts pages. A bigger cache keeps a
working set that won't fit in 2 MB out of the read path.
`temp_store = MEMORY` keeps the temporary tables and indices built for
sorts, `GROUP BY` and `DISTINCT` off disk. Neither setting is stored in
the file, so each connection sets both.

Source: <https://sqlite.org/pragma.html#pragma_cache_size>

> If the argument N is negative, then the number of cache pages is adjusted to be a number of pages that would use approximately abs(N*1024) bytes of memory based on the current page size.
> — SQLite 3.53.1 docs

> When you change the cache size using the cache_size pragma, the change only endures for the current session.
> — SQLite 3.53.1 docs

> When temp_store is MEMORY (2) temporary tables and indices are kept as if they were in pure in-memory databases.
> — SQLite 3.53.1 docs

**How.** Run both in the per-connection pragma list shown in SQLITE-002:

```python
import sqlite3

conn = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
conn.execute("PRAGMA cache_size = -65536")  # 64 MiB, not pages: negative means KiB
conn.execute("PRAGMA temp_store = MEMORY")
```

**When NOT to apply.** The cache is per connection. With one writer and
four readers that's up to 320 MiB, reached as the caches fill. Size it
for the host, and leave the default for small databases or constrained
containers. `temp_store = MEMORY` can use a lot of RAM for large sorts,
and a library compiled with `SQLITE_TEMP_STORE` can override it.

---

## SQLITE-013 — Batch many writes into one transaction (executemany)

**What.** Insert any number of rows with one `executemany` inside one
write transaction. A duplicate anywhere in the batch rolls back every
row.

**Why.** Every transaction pays a fixed cost at commit: taking and
releasing locks, appending the commit to the WAL, and, with
`synchronous = FULL`, an fsync. A statement outside `BEGIN` is its own
transaction, so a loop of single inserts pays that cost once per row. A
3,000-row benchmark (SQLite 3.53.1, local disk): defaults with a commit
per row, 151 rows/s. WAL with `synchronous = FULL`, 619. WAL with
`NORMAL`, 18,173. WAL with `NORMAL` and one `executemany` transaction,
1,425,256, which is 78× the commit-per-row rate with the same settings
and 9,467× the defaults. Absolute numbers depend on the disk; the ratios
are what carry over. The batch is also atomic.

Source: <https://sqlite.org/fasterthanfs.html>

> to get the most performance out of SQLite, you should group as much database interaction as possible within a single transaction.
> — SQLite 3.53.1 docs

**How.** `write()` is the `BEGIN IMMEDIATE` context manager from
SQLITE-005:

```python
from collections.abc import Iterable


def open_accounts(accounts: Iterable[tuple[str, int]]) -> int:
    with write() as conn:  # one BEGIN ... COMMIT around every row
        return conn.executemany(
            "INSERT INTO account (name, balance) VALUES (?, ?)", accounts
        ).rowcount
```

**When NOT to apply.** A long write transaction holds the only write lock
for as long as it runs, so other writers wait (up to `busy_timeout`) and
the WAL grows until the next checkpoint. Split huge imports into chunks
of a few thousand rows. Rows that have to commit independently, where
one failure mustn't discard the others, need their own transactions or
savepoints.

---

## SQLITE-014 — Know when not to use SQLite (network filesystems, many hosts or writers), and leave mmap_size off unless measured

**What.** Don't put this design on network filesystems (NFS, SMB), on a
database that several machines write to, or under sustained write
concurrency beyond one writer at a time. Leave `mmap_size` at its default
of off, on purpose.

**Why.** SQLite's locking relies on the filesystem, and many network
filesystems implement locking incorrectly, which lets two clients write
the same pages and corrupt the file. WAL also needs shared memory, so
every process has to be on one host (<https://sqlite.org/wal.html>).
SQLite runs one writer at a time, however many connections are open.
Memory-mapped I/O can speed up reads, but an I/O error on a mapped page
arrives as a signal (SIGBUS) that crashes the process, instead of an
error code, and it isn't always faster
(<https://sqlite.org/mmap.html>).

Source: <https://sqlite.org/whentouse.html>

> A good rule of thumb is to avoid using SQLite in situations where the same database will be accessed directly (without an intervening application server) and simultaneously from many computers over a network.
> — SQLite 3.53.1 docs

> SQLite supports an unlimited number of simultaneous readers, but it will only allow one writer at any instant in time.
> — SQLite 3.53.1 docs

**How.** Record the decision next to the connection setup, and leave the
pragma out:

```python
# Not set: PRAGMA mmap_size. An I/O error on a mapped page becomes SIGBUS instead of an
# error code, and the read speed-up depends on the platform; measure before turning it on.
# Not supported: network filesystems, several hosts, or more than one writer at a time;
# those need a client/server database such as PostgreSQL.
CONNECTION_PRAGMAS = (
    "PRAGMA foreign_keys = ON",
    "PRAGMA synchronous = NORMAL",
    "PRAGMA cache_size = -65536",
    "PRAGMA temp_store = MEMORY",
)
```

**When NOT to apply.** One host, one process or a few, where writes are
short and a queue of writers is acceptable (an app's local store, a
service's job queue, a cache, read-mostly websites): that's where SQLite
fits, and this design is built for it. Turn `mmap_size` on only after
measuring a read-heavy workload, on an OS known to have a unified buffer
cache.

---

## SQLITE-015 — Timestamps as UTC ISO-8601 TEXT generated by SQLite (strftime)

**What.** A timestamp column is
`TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))`: SQLite
stamps each row at insert, in UTC, with milliseconds and an explicit
`Z`, for example `2026-09-23T20:07:02.123Z`. The application never
supplies it.

**Why.** SQLite has no datetime type. One fixed-width UTC format sorts
correctly as text, compares correctly in SQL, and parses unambiguously in
any language. When SQLite generates it, every writer, whatever its
language, clock library or local time zone, produces the same format.
`CURRENT_TIMESTAMP` is UTC too, but its `YYYY-MM-DD HH:MM:SS` has no
fractional seconds and no zone marker. `'now'` is UTC per
<https://sqlite.org/lang_datefunc.html>.

Source: <https://sqlite.org/lang_createtable.html#dfltval>

> If the default value of a column is an expression in parentheses, then the expression is evaluated once for each row inserted and the results used in the new row.
> — SQLite 3.53.1 docs

> For CURRENT_TIME, the format of the value is "HH:MM:SS". For CURRENT_DATE, "YYYY-MM-DD". The format for CURRENT_TIMESTAMP is "YYYY-MM-DD HH:MM:SS".
> — SQLite 3.53.1 docs

**How.**

```python
import sqlite3

conn = sqlite3.connect("app.db", autocommit=True, timeout=5.0)
conn.execute(
    """CREATE TABLE IF NOT EXISTS event (
        id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
    ) STRICT"""
)
created_at = conn.execute(
    "INSERT INTO event DEFAULT VALUES RETURNING created_at"
).fetchone()[0]  # e.g. '2026-09-23T20:07:02.123Z'
```

**When NOT to apply.** When the time has to come from the application (an
event's own timestamp, or a clock that tests can control), pass it as a
bound parameter in the same format. Wall-clock local times that must keep
their zone (a meeting at 09:00 Europe/Paris) need the zone name stored
separately. Integer Unix time is more compact, if human readability
doesn't matter.
