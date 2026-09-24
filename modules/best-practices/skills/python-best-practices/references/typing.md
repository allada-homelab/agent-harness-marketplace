# PY typing rules

Detailed entries for `PY-010..PY-019` plus selected newer rules
(`PY-069`, `PY-071`). Each follows the four-part
**What / Why / How / When NOT to apply** shape.

Citations point at the
[Python typing docs](https://docs.python.org/3/library/typing.html),
[mypy docs](https://mypy.readthedocs.io/),
[pyright docs](https://microsoft.github.io/pyright/),
and the relevant PEPs (485, 526, 585, 604, 612, 673, 695, 696, 742).

---

## PY-010 — Use modern syntax: `X | Y`, `list[X]`, `Self`

**What.** Three syntactic upgrades available on modern Python:

| Old form (typing module) | New form | Available since |
|---|---|---|
| `Union[X, Y]` | `X \| Y` | 3.10 ([PEP 604](https://peps.python.org/pep-0604/)) |
| `Optional[X]` | `X \| None` | 3.10 |
| `typing.List[str]` | `list[str]` | 3.9 ([PEP 585](https://peps.python.org/pep-0585/)) |
| `typing.Dict[K, V]` | `dict[K, V]` | 3.9 |
| `typing.Type[X]` | `type[X]` | 3.9 |
| `-> "Builder"` (forward ref) | `-> Self` | 3.11 ([PEP 673](https://peps.python.org/pep-0673/)) |

For projects on 3.9 that need the union syntax: `from __future__
import annotations` at the top of the file enables it without
runtime cost.

**Why.** Three reasons:

1. **Consistency.** A codebase mixing `Optional[X]` and `X | None` signals it grew across different Python versions with no consistent migration — and readers can't tell which form is "current style." Ruff's `UP007`/`UP006` rules flag these automatically.
2. **Forward refs become real types.** `def make_child(self) -> "Builder": ...` is a string until evaluated; tools and IDEs sometimes get it wrong. `Self` (PEP 673) is a real type that does the right thing in subclasses without forward refs.
3. **`typing` module gets lighter.** `from typing import List, Dict, Optional, Union` was a Python idiom for a decade. None of those imports are needed on modern Python; dropping them shrinks every file's import block.

**How.**

```python
# 3.10+ — direct syntax
def fetch(url: str, headers: dict[str, str] | None = None) -> list[Item]:
    ...

class Builder:
    def with_name(self, name: str) -> Self:
        self._name = name
        return self

# 3.9 — needs the future import
from __future__ import annotations

def fetch(url: str, headers: dict[str, str] | None = None) -> list[Item]:
    ...
```

For `Self` on 3.9/3.10: `from typing_extensions import Self`.

**When NOT to apply.** Two narrow cases:

1. **Libraries supporting Python < 3.9.** Both Optional and `typing.List` are required. You're stuck on the old syntax.
2. **Code that uses annotations at runtime via `typing.get_type_hints()`** (FastAPI, Pydantic) — the new syntax mostly works, but a few edge cases (string-quoted union literals as type aliases) can break introspection. Test before bulk-migrating.

For everything else, modern syntax. Set `target-version = "py311"`
(or your floor) in `[tool.ruff]` and let `UP006`/`UP007` enforce it.

---

## PY-011 — Default to `pyright` (or `basedpyright`) for new projects

**What.** For greenfield projects in 2026, prefer
[pyright](https://microsoft.github.io/pyright/) (or
[basedpyright](https://github.com/DetachHead/basedpyright), the pip-installable
fork with stricter defaults). For projects already on `mypy`, stay
unless concrete conformance gaps block you.

Two fast new checkers have landed. **pyrefly** (Meta) reached a stable
**1.0** in May 2026 — >90% typing-spec conformance and roughly 10–50× the
speed of mypy/pyright — and is a legitimate option to evaluate for new
projects that don't need mypy plugins. Astral's `ty` is still in beta
(lower spec conformance) and has **no plugin system planned**, even
post-1.0 — which permanently blocks migration for any project relying on
the Django, SQLAlchemy, or attrs mypy plugins. So the recommendation
holds — pyright/basedpyright by default, mypy for plugin-dependent stacks
— with pyrefly now the speed-focused alternative worth a look.

**Why.** Two factors:

1. **Typing-spec conformance.** Pyright tracks ~95% of the typing spec; mypy is around 60%. Concretely: recent additions like `TypeVar` defaults (PEP 696), `ParamSpec` (PEP 612), variadic generics (PEP 646) work in pyright before mypy.
2. **Speed.** Pyright is written in TypeScript and runs incrementally; it's notably faster than mypy on large codebases. (`mypyc`-compiled mypy 1.x has closed some of this gap, but pyright still leads on cold runs.)

Why not just always pyright? Two real constraints:

- **Mypy plugins** (Django, SQLAlchemy ORM, attrs) — there's no pyright equivalent for many of these. Projects depending on them stay on mypy.
- **Switching cost.** Existing mypy configs and `# type: ignore[code]` comments are mypy-specific; pyright uses different error codes. Migration is a real project, not a flag flip.

**How.**

```toml
# pyproject.toml — pyright via basedpyright
[tool.pyright]
typeCheckingMode = "strict"
pythonVersion = "3.11"
include = ["src", "tests"]
exclude = ["**/node_modules", "**/__pycache__"]
```

```toml
# pyproject.toml — mypy strict
[tool.mypy]
python_version = "3.11"
strict = true
warn_unused_configs = true
exclude = ["build/", "dist/"]

# Per-module overrides
[[tool.mypy.overrides]]
module = ["legacy_module.*"]
ignore_errors = true
```

In CI:

```yaml
# pyright
- run: uvx basedpyright src/

# or mypy
- run: uv run mypy src/
```

**When NOT to apply.** When your stack depends on plugins only mypy
ships (Django models, SQLAlchemy 1.x mapped attributes, attrs
mixins). Audit `[tool.mypy] plugins = [...]` before switching.

---

## PY-012 — Configure strict mode

**What.** Both mypy and pyright support a strict mode that enables
all checks by default. Turn it on in `pyproject.toml`:

```toml
# mypy
[tool.mypy]
strict = true

# pyright / basedpyright
[tool.pyright]
typeCheckingMode = "strict"
```

For a more granular approach, mypy's `strict` flag is equivalent to
(the list `mypy --help` prints under `--strict`):

```toml
[tool.mypy]
disallow_any_generics = true
disallow_subclassing_any = true
disallow_untyped_calls = true
disallow_untyped_defs = true
disallow_incomplete_defs = true
check_untyped_defs = true
disallow_untyped_decorators = true
warn_redundant_casts = true
warn_unused_ignores = true
warn_return_any = true
no_implicit_reexport = true
strict_equality = true
extra_checks = true
```

`no_implicit_optional` isn't on that list because it has been mypy's
default since 0.990. `warn_unused_configs` isn't on it either. Set it
yourself so a typo'd override `module` pattern gets reported.

**Why.** Untyped Python is harder to refactor safely than typed
Python, and strict mode is the difference between "we have type
hints" and "type hints actually prevent bugs."

Three behaviors strict mode catches that loose mode silently
accepts:

1. **`disallow_untyped_defs`** — every function must have annotations. Loose mode treats `def foo(x):` as `def foo(x: Any) -> Any:`, which makes type errors invisible inside `foo`.
2. **`warn_unused_ignores`** — `# type: ignore[error-code]` on a line that no longer has that error fails the type check. Otherwise, ignores accumulate forever, masking new errors.
3. **`no_implicit_reexport`** — `from mymod import X` doesn't make `X` part of `mypackage`'s public API unless explicitly re-exported (via `__all__` or `from mymod import X as X`). Loose mode treats every import as re-exported, making the public API ambiguous.

**How.** Adopt strict mode incrementally on an existing codebase:

```toml
# Start: strict on by default, loose on legacy modules
[tool.mypy]
strict = true

[[tool.mypy.overrides]]
module = ["mypackage.legacy.*"]
# `strict` is global-only: `strict = false` here is silently ignored
disallow_untyped_defs = false
disallow_incomplete_defs = false
disallow_untyped_calls = false
check_untyped_defs = false

[[tool.mypy.overrides]]
module = ["mypackage.thirdparty_no_stubs.*"]
ignore_missing_imports = true
```

Then narrow the legacy override list over time as you add types
to those modules.

**When NOT to apply.** Brand-new exploratory scripts where you
genuinely don't know the types yet. Strict mode lights up the file
red and slows iteration. Promote to strict once the design is
settled.

---

## PY-013 — `Protocol` for structural interfaces; `abc.ABC` for enforced hierarchy

**What.** Two ways to declare an interface in Python:

| Mechanism | When |
|---|---|
| `typing.Protocol` | Structural / duck-typed interface. Any class with matching methods satisfies it, no inheritance required. |
| `abc.ABC` + `@abstractmethod` | Nominal interface. Subclasses must explicitly inherit. `isinstance()` checks work at runtime. |

```python
# Protocol — structural
from typing import Protocol

class Drawable(Protocol):
    def draw(self) -> None: ...

def render(obj: Drawable) -> None:
    obj.draw()       # Accepts any class with a .draw() method

# ABC — nominal
from abc import ABC, abstractmethod

class Transport(ABC):
    @abstractmethod
    def send(self, data: bytes) -> None: ...

class HTTPTransport(Transport):
    def send(self, data: bytes) -> None:
        ...
```

**Why.** Pick based on whether your interface is descriptive (any
fitting shape works) or prescriptive (must explicitly opt in):

1. **Protocol fits ecosystem code.** When a function accepts "anything that has a `.read()` method" (the file-like protocol), Protocol declares that without requiring third-party code to inherit from your base class. ABC would force `requests.Response` and `io.BytesIO` to both inherit a common ancestor, which they can't.
2. **ABC enforces opt-in.** When you want subclasses to *know* they're implementing the interface (so they can't accidentally satisfy it via duck-type collision), ABC makes the inheritance explicit. `class HTTPTransport(Transport)` is a declaration of intent.
3. **`isinstance()` semantics differ.** `isinstance(obj, MyProtocol)` requires `@runtime_checkable` and only checks method *existence* (not signatures or types). `isinstance(obj, MyABC)` is a real subclass check.

**How.** A practical rule of thumb:

- Use `Protocol` when **you don't own the implementations** (file-likes, callables, third-party types).
- Use `ABC` when **you own the hierarchy** and want explicit declaration (plugin systems, framework base classes).

```python
# Protocol for ecosystem-shaped types
class SupportsClose(Protocol):
    def close(self) -> None: ...

def cleanup(resources: list[SupportsClose]) -> None:
    for r in resources:
        r.close()

# ABC for plugin / framework base
class Plugin(ABC):
    name: str

    @abstractmethod
    def setup(self, app: App) -> None: ...

    @abstractmethod
    def teardown(self) -> None: ...

class MetricsPlugin(Plugin):
    name = "metrics"
    def setup(self, app: App) -> None: ...
    def teardown(self) -> None: ...
```

**When NOT to apply.** Don't reach for either when a plain function
signature works. If you have one place that takes one parameter,
just annotate the type. Interface abstractions earn their place when
you have multiple implementations or genuine plugin extensibility —
not for every shape that appears once.

---

## PY-014 — `TYPE_CHECKING` block + `from __future__ import annotations`

**What.** When an import is needed *only* for type annotations,
put it behind `if TYPE_CHECKING:` and add `from __future__ import
annotations` to the file.

```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from mypackage.heavy_module import BigClass

def process(items: Sequence[BigClass]) -> None:
    ...
```

**Why.** Two failure modes from getting this wrong:

1. **Circular imports.** Module A imports B for a type annotation; B imports A for a type annotation. Without `TYPE_CHECKING`, the import cycle is real and at least one module fails to load. With `TYPE_CHECKING`, the imports happen only for the type checker, not at runtime.
2. **Import-time performance.** `mypackage.heavy_module` may be slow to import (lots of dependencies, large LUTs at module level). If you only need its types for annotations, importing it at runtime is pure cost.

`from __future__ import annotations` (PEP 563) makes all
annotations strings at runtime, deferring evaluation. Combined with
`TYPE_CHECKING`, this lets you write annotations that reference
modules that aren't imported at runtime — pyright and mypy still see
the types, but Python itself never evaluates them.

On **Python 3.14+**, deferred annotation evaluation (PEP 649/749) is the
default, so the future import is no longer needed for forward references
or for the `TYPE_CHECKING` pattern — though it still works and is not yet
deprecated (see PY-080). The `if TYPE_CHECKING:` block itself stays
necessary regardless of version: deferred evaluation fixes *forward
references*, but the import cycle is still real at runtime if the import
isn't guarded. Libraries that introspect annotations at runtime (Pydantic,
FastAPI) still need the guarded imports resolvable.

**How.**

```python
# my_module.py
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # only the type checker sees these
    from .other import OtherClass
    from collections.abc import Iterable

class MyClass:
    def process(self, items: Iterable[OtherClass]) -> None:
        # body — no need to import OtherClass for runtime
        for item in items:
            self._handle(item)
```

**The "runtime needs the type" exception.** Some libraries
(`pydantic.BaseModel`, FastAPI, attrs with validators) introspect
annotations at runtime via `typing.get_type_hints()`. For those,
`TYPE_CHECKING` *doesn't work* — the type needs to actually be
importable. In those modules, import normally (without the
`TYPE_CHECKING` block) for the runtime-introspected types, and use
`TYPE_CHECKING` only for purely-static annotations.

**When NOT to apply.** Single-file scripts and small modules where
circular imports aren't a concern — the boilerplate isn't worth it.
For libraries and larger applications: default to `TYPE_CHECKING`
for type-only imports.

---

## PY-015 — `TypedDict` / `@dataclass` / `pydantic.BaseModel` decision matrix

**What.** Pick the data container based on what you actually need:

| Container | Best for | Cost |
|---|---|---|
| `TypedDict` | Typing the shape of JSON / API responses you already have | Zero runtime cost |
| `@dataclass` | Internal records, config structs, value objects | Stdlib; minimal runtime cost |
| `@dataclass(frozen=True)` / `NamedTuple` | Immutable, hashable records | Same as dataclass |
| `pydantic.BaseModel` | Validating untrusted input (API requests, env config) | Runtime validation; extra dependency |
| `attrs.define` | When you need dataclass features mypy doesn't fully support (validators, converters) | Extra dep; powerful |

**Why.** The trap is using one tool for everything:

1. **`pydantic` everywhere.** Pydantic does runtime validation. That's its value at API boundaries — but inside the application, you have *already validated* data. Re-validating on every internal data passing wastes CPU and forces an unnecessary dependency. A 50-field internal record that uses `BaseModel` is paying validation cost for data that was validated at the entrypoint hours ago.
2. **`TypedDict` for user input.** TypedDict provides *typing* but not *validation*. If you receive `{"age": "not_a_number"}` from an HTTP request and parse it as `User: TypedDict[{"age": int}]`, mypy thinks `user["age"]` is an int — but at runtime it's the string `"not_a_number"`. Type-checker says "fine," runtime says `TypeError` when you do arithmetic.
3. **`@dataclass` for ad-hoc dicts.** When the data is genuinely shaped like a dict (it comes from JSON, it'll go back to JSON, you index it by key), forcing it into a dataclass adds friction (`.field` syntax, custom serializers).

The decision is one question: *where does this data come from, and
who is responsible for validating it?*

**How.**

```python
# TypedDict — pure shape, no validation
from typing import TypedDict

class UserDict(TypedDict):
    id: int
    name: str
    email: str

def parse_user(raw: dict) -> UserDict:
    return raw   # type narrowing only; assumes raw was validated upstream

# Dataclass — internal record, mutable
from dataclasses import dataclass

@dataclass
class Connection:
    host: str
    port: int
    retries: int = 3

# Frozen dataclass — immutable, hashable
@dataclass(frozen=True)
class Coordinate:
    x: float
    y: float

# Pydantic — validating input at a boundary
from pydantic import BaseModel, EmailStr

class CreateUserRequest(BaseModel):
    name: str
    email: EmailStr        # validated
    age: int = Field(ge=0, le=150)

# Use the validated model at the boundary, then convert to a dataclass for internal use:
def handle_create_user(req: CreateUserRequest) -> User:
    return User(name=req.name, email=req.email, age=req.age)
```

**When NOT to apply.** Two real exceptions:

1. **Codebases that use Pydantic as the framework's data shape (FastAPI is the canonical example).** When the framework already does request/response validation via Pydantic, sticking with Pydantic for internal data avoids constant conversion. The "validation cost" is amortized over the framework's benefit.
2. **Microservices with heavy serialization round-trips.** When the same shape is hydrated/dehydrated frequently, a serialization-friendly framework (Pydantic, `msgspec`) may be a better default than `@dataclass` + manual `to_dict()` / `from_dict()` everywhere.

---

## PY-016 — `# type: ignore[code]` and `# noqa: CODE` always with explicit code

**What.** Suppression comments must name the rule:

```python
# CORRECT
result = some_untyped_lib.get()  # type: ignore[no-any-return]
import os  # noqa: F401  (intentionally unused, re-exported)

# WRONG — bare suppression
result = some_untyped_lib.get()  # type: ignore
import os  # noqa
```

**Why.** Bare suppressions are a long-term tax:

1. **They swallow future errors silently.** A bare `# type: ignore` suppresses *every* type error on that line, forever. Later, when a real type error appears on the same line (you refactored something, the library changed), it's silently hidden. The bug surfaces in production, not in CI.
2. **They can't be cleaned up.** `# noqa` without a code can't be flagged as "the suppressed rule no longer fires." With the code, ruff's `RUF100` rule flags any `# noqa: F401` on a line that doesn't have `F401` anymore.
3. **They obscure intent.** `# type: ignore  # mypy is wrong here` doesn't tell future readers *what* mypy was wrong about. `# type: ignore[arg-type]` does.

mypy's `warn_unused_ignores = true` (part of strict mode, PY-012)
catches `# type: ignore` lines that no longer have an error — but
only when the code is included. Bare ignores escape this check.

**How.**

```python
# Right way
def process(data):  # type: ignore[no-untyped-def]
    # legitimately untyped: third-party callback signature
    return data * 2

# Multiple codes on the same line
result = library_call()  # type: ignore[no-any-return, attr-defined]

# Always include a one-line reason if it's not obvious
config_loader = LegacyConfigLoader()  # type: ignore[abstract]  # legacy concrete class lacks @final marker
```

For ruff:

```python
import os  # noqa: F401  — re-exported from this module
import unused_import  # noqa: F401  — keeps backwards compat with v1 API
```

Enable detection of unused suppressions:

```toml
[tool.ruff.lint]
select = ["RUF100"]   # PY-025 — flag unused noqa
```

```toml
[tool.mypy]
warn_unused_ignores = true   # part of strict mode
```

**When NOT to apply.** Never. Bare ignores are always wrong; the
rule has no real exceptions. If the code is *truly* unsuppressable
(third-party library breaks the type checker in some weird way), at
least pick the most specific error code and document with a comment.

---

## PY-069 — Prefer `TypeIs` over `TypeGuard` for narrowing predicates

**What.** For user-defined type-narrowing predicates, return
[`TypeIs[T]`](https://peps.python.org/pep-0742/) (PEP 742, Python
3.13+ — or `typing_extensions ≥ 4.10` on older interpreters) rather
than the older `TypeGuard[T]`.

```python
from typing import TypeIs, assert_never

class Cat:
    ...

class Dog:
    ...

Animal = Cat | Dog

def is_cat(a: Animal) -> TypeIs[Cat]:
    return isinstance(a, Cat)

def describe(a: Animal) -> str:
    if is_cat(a):
        return f"cat {a}"           # narrowed to Cat
    else:
        return f"dog {a}"           # narrowed to Dog (NOT Animal)
```

**Why.** `TypeGuard` only narrows in the **positive** branch:

```python
from typing import TypeGuard, assert_never

def is_cat(a: Animal) -> TypeGuard[Cat]:
    return isinstance(a, Cat)

def describe(a: Animal) -> str:
    if is_cat(a):
        return f"cat {a}"           # narrowed to Cat — OK
    else:
        assert_never(a)             # ERROR — a is still Animal here
```

In the `else` branch, `TypeGuard` does *not* subtract the narrowed
type from the original. That breaks `assert_never`-style
exhaustiveness checks on union types — the most common reason to
write a narrowing predicate in the first place.

`TypeIs[T]` does the right thing in both branches: positive branch
narrows to `T`, negative branch narrows to `Original - T`. This is
the behavior most users expected from `TypeGuard` and is the reason
PEP 742 exists.

**How.** Default to `TypeIs[T]` everywhere:

```python
from typing import TypeIs

def is_str_list(xs: list[object]) -> TypeIs[list[str]]:
    return all(isinstance(x, str) for x in xs)

def total_length(xs: list[object]) -> int:
    if is_str_list(xs):
        return sum(len(s) for s in xs)   # xs: list[str]
    return 0
```

For pre-3.13 support: `from typing_extensions import TypeIs`. Same
semantics; same name.

**When NOT to apply.** `TypeGuard` is still the right tool in the
one case PEP 742 explicitly preserves: when the **narrowed type is
deliberately wider** than the input, so the negative-branch
narrowing would be wrong. Example: a predicate over `list[object]`
that returns `TypeGuard[list[int]]` to mean "this list is safe to
treat as `list[int]` for our purposes, even though some elements
might not actually be ints." In that case `TypeIs` would mis-narrow
the `else`. This is rare; reach for it only when the asymmetry is
intentional.

---

## PY-071 — Use PEP 695 generic syntax (3.12+)

**What.** On Python 3.12+, use the inline generic syntax introduced
by [PEP 695](https://peps.python.org/pep-0695/) — `def foo[T]() -> T`, `class Box[T]:`, `type Alias = list[int]` — instead of the older
`TypeVar` + `Generic[T]` + `TypeAlias` machinery.

```python
# PEP 695 — 3.12+
def first[T](items: list[T]) -> T:
    return items[0]

class Box[T]:
    def __init__(self, value: T) -> None:
        self.value = value

type JSON = dict[str, "JSON"] | list["JSON"] | str | int | float | bool | None
```

The equivalent in the pre-695 idiom:

```python
from typing import Generic, TypeVar, TypeAlias

T = TypeVar("T")

def first(items: list[T]) -> T:
    return items[0]

class Box(Generic[T]):
    def __init__(self, value: T) -> None:
        self.value = value

JSON: TypeAlias = "dict[str, JSON] | list[JSON] | str | int | float | bool | None"
```

**Why.** Three concrete benefits:

1. **Scoped type parameters.** With PEP 695, `T` exists only on the function or class it's declared on. With the old `T = TypeVar("T")`, `T` is module-global; two functions in the same file accidentally sharing `T` look like they share a type parameter (because they do, at the module level) when each really wanted its own. This causes subtle "should be independent" bugs in libraries with many generic helpers.
2. **No `typing` import for the common case.** Generic functions, classes, and aliases no longer need any `from typing import ...` line. Smaller import blocks, less ceremony.
3. **Real `type` statement.** The new `type Alias = ...` is a *statement*, not a variable assignment with a `TypeAlias` annotation. Forward references inside the alias (`type JSON = dict[str, "JSON"] | ...`) work lazily without `from __future__ import annotations`. Generic aliases (`type Pair[T] = tuple[T, T]`) work directly.

[PEP 696](https://peps.python.org/pep-0696/) layers type-parameter
defaults on top — `class Box[T = str]:` — but is **3.13+**, not
3.12. Pin your `requires-python` accordingly before relying on
defaults.

Ruff's `UP` family does **not** currently rewrite legacy `TypeVar`
declarations into PEP 695 syntax (as of early 2026) — the migration
is correctness-sensitive (scope changes, bound/variance preservation,
typing_extensions fallbacks) and is left to humans. Don't expect
`ruff check --fix` to do this for you.

**How.** Migrate one declaration at a time:

```python
# Generic class with a bound
class Repository[ItemT: BaseItem]:
    def get(self, id: int) -> ItemT: ...

# Generic class with a constraint (multiple specific types)
class Comparable[T: (int, float, str)]:
    def cmp(self, a: T, b: T) -> int: ...

# Variance — PEP 695 uses Self-explanatory prefix
class Producer[T]:                 # invariant by default
    def produce(self) -> T: ...

class Consumer[T_contra]:          # convention — name-suffix indicates intent
    def consume(self, x: T_contra) -> None: ...

# Generic alias (3.12+)
type Pair[T] = tuple[T, T]
type Result[T, E] = T | E
```

For variance specifically, PEP 695 still expresses
covariance/contravariance via the older `TypeVar(..., covariant=True)`
spelling when truly needed — but most generic types are invariant
and don't need it.

**When NOT to apply.** Two cases:

1. **Libraries supporting Python < 3.12.** The PEP 695 syntax is a parse-time feature; older interpreters can't even *import* the file. Use `typing.TypeVar` + `Generic` until you can drop 3.11.
2. **Code relying on `TypeVar` introspection at runtime.** Some libraries (older versions of pydantic, attrs internals) reflect on `__type_params__` / `__parameters__`. PEP 695 changes how those attributes are populated; spot-check the library before bulk migration.

## PY-080 — On Python 3.14+, drop `from __future__ import annotations`

**What.** Python 3.14 makes deferred annotation evaluation (PEP 649 +
PEP 749) the default, so `from __future__ import annotations` is no
longer needed for forward references or type-only annotations. Once a
project's floor is 3.14+, removing the import is reasonable cleanup —
but it is **optional**, not a correctness fix: the import still works and
is **not yet deprecated** (a `DeprecationWarning` is expected only after
Python 3.13 reaches end-of-life, ~2029).

**Why.** Keeping a now-unnecessary import is harmless, but on a
3.14+-only codebase it's dead style that suggests the file predates the
default change. Removing it is a small clarity win — don't rush it, and
don't treat its presence as a bug.

**How.**

```python
# Python 3.14+ floor — forward refs work without the import
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mypackage.heavy import BigClass

def process(x: BigClass) -> None: ...
```

The `UP` ruff family does not (yet) remove the future import for you —
do it by hand when you raise `requires-python` to `>=3.14`.

**When NOT to apply.** Any project still supporting Python 3.9–3.13 —
there the import is still load-bearing for forward refs and the
`TYPE_CHECKING` pattern (PY-014). And keep the `if TYPE_CHECKING:` guard
itself regardless of version: deferred evaluation fixes forward
references, not the runtime import cycle.

---

## PY-081 — Use `TypedDict(closed=True)` / `extra_items=` for strict JSON shapes

**What.** PEP 728 (finalized, targeting Python 3.15; available earlier
via `typing_extensions`) adds `closed=True` to a `TypedDict` to reject
untyped extra keys, and `extra_items=SomeType` to type additional keys.

**Why.** A plain `TypedDict` silently *accepts* extra keys not in its
definition, so a TypedDict meant to model a fixed API contract says
nothing about unexpected fields and structural narrowing stays
incomplete. `closed=True` makes the contract actually closed;
`extra_items=` types an open-ended map with a known value type.

**How.**

```python
from typing import TypedDict   # or typing_extensions pre-3.15

class UserResponse(TypedDict, closed=True):   # no keys beyond these allowed
    id: int
    name: str

class Headers(TypedDict, extra_items=str):    # arbitrary string-valued keys
    content_type: str
```

**When NOT to apply.** Dictionaries that legitimately carry arbitrary
keys you don't model — leave them open. And on pre-3.15 without
`typing_extensions ≥ 4.12`, the syntax isn't available.

---

## PY-082 — Use `TypeForm[T]` for functions that accept a type expression at runtime

**What.** PEP 747 (finalized, targeting Python 3.15; `typing_extensions`
earlier) introduces `TypeForm[T]` — the correct annotation for a
parameter that receives a *type expression* such as `int | None`,
`list[str]`, or `Annotated[X, ...]` at runtime.

**Why.** Before `TypeForm`, such parameters had to be typed `type[T]`
(wrong — `type[T]` rejects unions and special forms) or `Any` (unsound,
no checking). Runtime validators, adapters, and converters that take "a
type to validate against" finally have a precise, checkable type.

**How.**

```python
from typing import TypeForm   # or typing_extensions pre-3.15

def validate[T](shape: TypeForm[T], value: object) -> T:
    ...

validate(int | None, x)        # accepted; type[T] would reject the union
```

**When NOT to apply.** Parameters that only ever receive a concrete
class (not a union or special form) — `type[T]` is the right, narrower
type there.

---
