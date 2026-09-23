# PG rules

Detailed entries for `PG-001`, `PG-003..PG-005` and `PG-013`. Each follows
the four-part **What / Why / How / When NOT to apply** shape. Numbers
missing from the sequence are reserved; don't reuse them.

The snippets use SQLAlchemy 2.0 (async engine, `postgresql+psycopg`
driver) and Alembic 1.20. Quotes are verbatim from the SQLAlchemy 2.0.54,
Alembic 1.20.0 and PostgreSQL 18.6 docs. Wiring the engine and sessions
into a FastAPI app is covered by
[FAPI-071](../../fastapi-best-practices/references/async-db.md) in
`fastapi-best-practices`.

---

## PG-001 — Size the per-process pool against max_connections; pre-ping and recycle pooled connections

**What.** Create the async engine with `pool_size` and `max_overflow`
taken from settings (5 + 5 by default), plus `pool_pre_ping=True` and
`pool_recycle=1800`.

**Why.** Each process can hold up to `pool_size + max_overflow`
connections, and Postgres refuses connections past `max_connections`
(typically 100). So `replicas × (pool_size + max_overflow)` has to stay
under it, with headroom for the migrate job and admin sessions, or a
scale-out starts failing with "too many clients". Making both knobs
settings means that sum is set per deployment instead of hard-coded.
`pool_pre_ping` tests each connection at checkout and replaces one the
server dropped (restart, failover, killed idle TCP), so a request doesn't
fail on a stale connection. `pool_recycle` replaces a connection at
checkout once it is older than 30 minutes, which bounds how long any one
connection lives.

Sources: <https://docs.sqlalchemy.org/en/20/core/pooling.html#disconnect-handling-pessimistic>,
<https://www.postgresql.org/docs/18/runtime-config-connection.html#GUC-MAX-CONNECTIONS>

> The approach adds a small bit of overhead to the connection checkout process, however is otherwise the most simple and reliable approach to completely eliminating database errors due to stale pooled connections.
> — SQLAlchemy 2.0.54 docs

> This parameter prevents the pool from using a particular connection that has passed a certain age
> — SQLAlchemy 2.0.54 docs

> Determines the maximum number of concurrent connections to the database server. The default is typically 100 connections
> — PostgreSQL 18.6 docs

**How.**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="APP_", frozen=True)

    database_url: str = "postgresql+psycopg://app@localhost:5432/app"
    # Per-process pool. Size it against Postgres's max_connections across every replica:
    # replicas x (pool_size + max_overflow) must stay below it, with headroom for migrations and admin.
    pool_size: int = 5
    max_overflow: int = 5


# Called once per process (in the app's lifespan), never per request.
def make_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(
        settings.database_url,
        pool_size=settings.pool_size,
        max_overflow=settings.max_overflow,
        pool_pre_ping=True,  # replace a connection the server dropped before handing it out
        pool_recycle=1800,  # replace any connection older than 30 minutes
    )
```

**When NOT to apply.** Behind a transaction-mode pooler (PgBouncer), let
the pooler pool: use `NullPool` in the app. `pool_recycle` goes by
connection *age* since it was opened, not by idle time, so it doesn't
protect against a middlebox with a shorter idle timeout. `pool_pre_ping`
is what catches that case. Pre-ping costs a round trip per checkout,
which is only worth measuring at very high checkout rates.

---

## PG-003 — Serialize concurrent migrators with a transaction-scoped advisory lock (pg_advisory_xact_lock) inside Alembic's migration transaction

**What.** Alembic's `env.py` opens the migration transaction and runs
`SELECT pg_advisory_xact_lock(<key>)` before `context.run_migrations()`.
A second migrator blocks on that statement until the first one commits.
It then reads the now-current `alembic_version` and has nothing left to
apply. Four `alembic upgrade head` processes started together against an
empty database all exit 0, with each migration applied once.

**Why.** Replicas that each run a migrate job on deploy can start
together. Without a lock, they all read "no version" and run the same
`CREATE TABLE`, and the losers fail the deploy. The lock is
transaction-scoped, so it is released automatically at `COMMIT` or
`ROLLBACK`: a migrator that crashes or loses its connection can't leave
it held, and there's no unlock call to forget. Waiting in the server (a
blocking lock) needs no retry loop in the client.

Sources: <https://www.postgresql.org/docs/18/functions-admin.html#FUNCTIONS-ADVISORY-LOCKS>,
<https://www.postgresql.org/docs/18/explicit-locking.html#ADVISORY-LOCKS>

> Obtains an exclusive transaction-level advisory lock, waiting if necessary.
> — PostgreSQL 18.6 docs

> Transaction-level lock requests, on the other hand, behave more like regular lock requests: they are automatically released at the end of the transaction, and there is no explicit unlock operation.
> — PostgreSQL 18.6 docs

**How.** `migrations/env.py`, online mode only (offline mode emits SQL
without connecting, so there is nothing to lock):

```python
import asyncio

from alembic import context
from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base
from app.settings import Settings

# Any fixed 64-bit number, unique to this app's migrations, shared by every migrator.
MIGRATION_LOCK_KEY = 7_310_001


def run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        # Released automatically at COMMIT or ROLLBACK, so a crashed migrator can't leave it held.
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": MIGRATION_LOCK_KEY}
        )
        context.run_migrations()


async def run_online(url: str) -> None:
    # NullPool: a migration run is one connection, once; there's nothing to pool.
    engine = create_async_engine(url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(run_migrations)
    finally:
        await engine.dispose()


asyncio.run(run_online(Settings().database_url))
```

**When NOT to apply.** The lock lasts one transaction. If the run is split
across several (`transaction_per_migration=True`, or a migration that
commits so it can run `CREATE INDEX CONCURRENTLY`), check that the lock
still covers the whole run, or take a session-level lock on a dedicated
connection instead. A blocking lock has no deadline: a migrator stuck
holding it stalls every other one. Set `lock_timeout` if a deploy must
fail fast rather than wait.

---

## PG-004 — Test that the models match the migrated schema (Alembic compare_metadata); migrations are reviewed, not trusted from autogenerate

**What.** A test applies the real migrations to Postgres, runs
`alembic.autogenerate.compare_metadata(MigrationContext.configure(conn), Base.metadata)`,
and asserts the diff is empty. Migrations are written and reviewed by
hand. Each migration names every constraint with `op.f(...)`, following
the models' `naming_convention`, so constraint names are deterministic.

**Why.** The ORM models and the migrations are two descriptions of one
schema, and nothing else keeps them in step. If they drift, the next
`alembic revision --autogenerate` emits a change nobody meant to write,
or the app expects a column or constraint production doesn't have.
Autogenerate only produces a candidate and misses some changes, so every
migration is reviewed. The test is what catches a model edit that
shipped without its migration.

Source: <https://github.com/sqlalchemy/alembic/blob/rel_1_20_0/docs/build/autogenerate.rst>

> It is *always* necessary to manually review and correct the **candidate migrations** that autogenerate produces.
> — Alembic 1.20.0 docs

> When ``alembic check`` returns a success code, this is an indication that the ``alembic revision --autogenerate`` command would produce only empty migrations, and does not need to be run.
> — Alembic 1.20.0 docs

**How.** `migrated` is a fixture yielding the URL of a test database that
`alembic upgrade head` has already run against:

```python
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import URL, create_engine

from app.models import Base


def test_the_models_match_the_migrated_schema(migrated: URL) -> None:
    engine = create_engine(migrated)
    try:
        with engine.connect() as conn:
            diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    finally:
        engine.dispose()
    assert diff == []
```

**When NOT to apply.** The check only sees what autogenerate can detect:
renames look like drop plus add, and some type and server-default changes
are invisible. `alembic check` is the same comparison as a CLI command,
for projects that would rather gate in CI than in a test.
`compare_metadata` is the older diff-tuple API, and `produce_migrations`
is its structured counterpart.

---

## PG-005 — Test each migration's upgrade → downgrade → upgrade round trip against the real Postgres image

**What.** A test creates an empty database on a testcontainers Postgres
running the same digest-pinned image as the deployment. It upgrades to
`head`, downgrades to `base` (only `alembic_version` is left), then
upgrades to `head` again.

**Why.** `downgrade()` is code nobody runs until they need a rollback,
which is the worst time to find out it's broken. Upgrading again after
the downgrade proves the downgrade removed everything the upgrade
created: a leftover index, type or constraint makes the second upgrade
fail. It runs on real Postgres because DDL behaviour differs between
databases.

Source: <https://github.com/sqlalchemy/alembic/blob/rel_1_20_0/docs/build/tutorial.rst>

> Typically, ``upgrade()`` is required while ``downgrade()`` is only needed if down-revision capability is desired, though it's probably a good idea.
> — Alembic 1.20.0 docs

**How.** `fresh_database` is a fixture yielding the URL of a newly
created, empty database; `env.py` reads the URL from
`config.attributes["url"]` when it is set:

```python
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import URL, create_engine, inspect

ROOT = Path(__file__).resolve().parents[1]


def alembic_config(url: URL) -> Config:
    config = Config(ROOT / "alembic.ini")
    config.attributes["url"] = url
    return config


def table_names(url: URL) -> set[str]:
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            return set(inspect(conn).get_table_names())
    finally:
        engine.dispose()


def test_migrations_upgrade_downgrade_and_upgrade_again(fresh_database: URL) -> None:
    config = alembic_config(fresh_database)
    command.upgrade(config, "head")
    assert {"account", "transfer"} <= table_names(fresh_database)
    command.downgrade(config, "base")
    assert table_names(fresh_database) == {"alembic_version"}
    command.upgrade(config, "head")
    assert {"account", "transfer"} <= table_names(fresh_database)
```

**When NOT to apply.** It proves the schema round-trips on an empty
database, not that data survives. Data migrations need their own tests
with rows in place. Irreversible migrations (dropping data) can't
round-trip. Their `downgrade()` should raise, and they should be left out
of this test on purpose. Testing one Postgres major, the pinned image, is
enough for an application. A library supporting several majors should
run it as a version matrix in CI.

---

## PG-013 — Lock every row a transaction will change with SELECT … FOR UPDATE, in one consistent order (ORDER BY id)

**What.** A transfer runs one transaction. It locks both accounts with
`SELECT … WHERE id IN (source, target) ORDER BY id FOR UPDATE`, checks
the source balance on the locked rows, updates both, and inserts the
transfer. Opposite-direction transfers running concurrently neither
deadlock nor lose money.

**Why.** Two transfers in opposite directions (A→B and B→A) that each
lock their own source row first will deadlock. Each holds one row and
waits for the other, and Postgres aborts one of them. Locking in
ascending id order means both queue on the lower id, so one waits and
neither fails. Postgres sorts before it locks, so `ORDER BY id` is the
order the locks are taken in. `FOR UPDATE` is the strongest row lock the
later `UPDATE` needs, so no lock is upgraded mid-transaction. The balance
check reads rows nobody else can change before `COMMIT`, so concurrent
transfers can't overdraw. The `balance >= 0` check constraint is a
backstop, not the mechanism.

Sources: <https://www.postgresql.org/docs/18/explicit-locking.html#LOCKING-DEADLOCKS>,
<https://www.postgresql.org/docs/18/sql-select.html#SQL-FOR-UPDATE-SHARE>

> The best defense against deadlocks is generally to avoid them by
> being certain that all applications using a database acquire
> locks on multiple objects in a consistent order.
> — PostgreSQL 18.6 docs

> One should also ensure that the first lock acquired on
> an object in a transaction is the most restrictive mode that will be
> needed for that object.
> — PostgreSQL 18.6 docs

> This is because <literal>ORDER BY</literal> is applied first.
> The command sorts the result, but might then block trying to obtain a lock
> on one or more of the rows.
> — PostgreSQL 18.6 docs

**How.**

```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Account, Transfer


class InsufficientFundsError(Exception):
    pass


async def transfer(
    session: AsyncSession, source_id: int, target_id: int, amount: int
) -> Transfer:
    async with session.begin():
        # Every transfer locks in ascending id order, so A->B and B->A queue instead of deadlocking.
        locked = await session.scalars(
            select(Account)
            .where(Account.id.in_((source_id, target_id)))
            .order_by(Account.id)
            .with_for_update()
        )
        accounts = {account.id: account for account in locked}
        if accounts[source_id].balance < amount:
            raise InsufficientFundsError(f"account {source_id} can't cover {amount}")
        accounts[source_id].balance -= amount
        accounts[target_id].balance += amount
        record = Transfer(source_id=source_id, target_id=target_id, amount=amount)
        session.add(record)
    return record
```

Reject `source_id == target_id` and missing accounts before indexing
`accounts`; both are omitted here.

**When NOT to apply.** A single-row change doesn't need an explicit lock:
`UPDATE … SET balance = balance - :x WHERE id = :id AND balance >= :x` is
atomic. Under `READ COMMITTED`, if the sort column can change
concurrently, rows can come back out of order (ids never change here).
Hot rows serialize every transaction that touches them. For queues use
`SKIP LOCKED`, and for invariants that span many rows consider
`SERIALIZABLE` with retries.
