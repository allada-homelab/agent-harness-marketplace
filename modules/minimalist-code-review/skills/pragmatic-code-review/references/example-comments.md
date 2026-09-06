# Example review comments by lens

A bank of example comments in this review style, grouped by lens, each with the
kind of code context that prompts it. The code is illustrative and generic — the
point is the *shape of the concern* and the *phrasing*, which transfer to any
stack. The principles live in `SKILL.md`; these are calibration.

Each example is: a short description of the code, then the comment.

## Necessity & over-engineering

> **code:** a helper that coerces a header value through `str → float → int`,
> handling `None`, missing keys, and several string formats.
> "why do we have to handle so many cases? the type of this value should be
> deterministic, right? can we just handle what it actually is rather than every
> possible type?"

> **code:** a new optional `delay: int = 0` parameter threaded into a background
> job, with no caller passing it.
> "why do we need to support a delay? is there a caller that needs it, or can we
> drop the param?"

> **code:** a `enable_legacy_mode=False` branch that forks the write path with a
> HEAD-then-PUT fallback, toggled only by tests.
> "do we need this branch? nothing in the app turns it off, and it forks the
> write path in three places we'd have to keep in sync. YAGNI — we can add it back
> the day we actually need it."

> **code:** a 280-line wrapper class that re-implements every method of the class
> it wraps, just to re-validate one invariant.
> "this is a lot of surface area for one check. could we fold the invariant into
> the wrapped class as a frozen attribute instead of a full passthrough wrapper?"

> **code:** a function with two large, nearly symmetric `if isinstance(cfg, A) /
> elif isinstance(cfg, B)` blocks.
> "these two legs are nearly identical — same where-clause assembly, same select,
> same call. ooc, did you consider pulling the shared scaffolding into a helper
> and passing in just the type-specific bits? the duplication is a bit loud."

> **code:** a `TypeAlias` introduced for a type used directly in two places.
> "ooc — why is this typealias necessary instead of using the type directly?"

> **code:** a new wrapper primitive added to drain in-flight work before
> teardown, justified by a crash if teardown races the work — added in the same
> PR as a lock that already serializes teardown against that work.
> "doesn't the lock you added already prevent the crash here? with it in place a
> late access raises a clean exception, not a segfault — so what's the wrapper
> defending against on top of the lock? if there's a real gap, can we get a test
> that reproduces the crash *with* the lock but *without* the wrapper? i'd rather
> not ship the mechanism on a plausible story alone."

> **code:** that same draining wrapper applied at a call site where the wrapped
> function touches none of the resource it's meant to protect.
> "this path doesn't touch the resource the wrapper guards, so the wrapper buys
> nothing here — can we just use the plain call? (we already do exactly that in
> [sibling files])."

> **code:** a guard added for an input shape, where the function is only ever
> called from one place that always passes the valid shape.
> "can this shape actually reach here? the only caller always passes a valid one
> — if so this guard is defending a case that can't occur, and we can drop it."

## Determinism & types

> **code:** a `@validator` that does `if not isinstance(data, dict): return data`
> before mutating it.
> "is `data` a dict or not a dict? we should deterministically handle the type it
> actually is, rather than guarding both ways."

> **code:** a model field `status: str` where the comment lists "active, paused,
> archived".
> "should this be an enum? that list reads like a closed set."

> **code:** a field declared `Optional[str]` that the surrounding model always
> populates.
> "is this ever actually None? if the model guarantees it, let's make it
> non-optional so callers don't have to None-check."

## Reuse & consolidation (DRY)

> **code:** a new `_fetch_active_users(...)` added next to an existing
> `_fetch_all_users(...)` with ~80% overlapping body.
> "why is this a separate helper from `_fetch_all_users`? can we update
> `_fetch_all_users` to accept a filter param and reuse it for the active case?"

> **code:** an `InvalidInput` exception defined in a new module.
> "this exception already exists in the tools module — is there a reason it was
> redefined rather than imported?"

> **code:** a helper `_safe_int` added in one file that is byte-identical to one
> in another.
> "this looks duplicated from the helper in the other module — can we import the
> existing one?"

> **code:** a new shared `save_result(...)` helper that two tools now call, while
> a third place still hand-rolls the same write-then-append-a-path-line dance.
> "nice that this folds the two tools into one helper — and it mirrors the block
> already in [other module]. since it's now the canonical version, should that
> third copy route through it too? otherwise we've got three near-identical
> persist paths that'll drift."

## Performance & query cost

> **code:** `.where(is_authorized_for(user_id, tenant_id))` as the first filter in
> a query over a large table.
> "should we filter by `tenant_id` first so we don't run `is_authorized_for` on
> everything? that predicate is probably more expensive than a column equality."

> **code:** a backend client constructed at the top of a function, before any of
> the input-validation guards.
> "the client gets allocated and thrown away on every invalid-input call (the most
> common first-touch error). can we move the construction down to just before
> it's actually used, after the guards pass?"

> **code:** a feature-flag lookup placed inside a model validator that runs on
> every request.
> "calling the flag check in a validator feels like a layering concern — it runs
> on every request, not just the ones that need it, so we're making a flag call
> each time. should this guard live where the feature is actually invoked?"

## Naming

> **code:** a new parameter `user` where sibling functions use `users`.
> "nit: let's rename to `users` to be consistent with the other parameter names."

> **code:** a method `full_text_search` that is internal and returns a query
> object rather than results.
> "can we rename to something like `_full_text_query` to indicate it's internal
> and that it returns a query, not results?"

> **code:** a file named `_archive.py` (leading underscore) in a package where no
> other module is underscore-prefixed.
> "nit: why the leading `_` on the filename? that isn't really a pattern we use
> elsewhere."

## Language footguns / idiom

> **code:** a Pydantic field `items: list[str] = []`.
> "we should prefer `Field(default_factory=list)` here — a mutable `= []` default
> is shared across instances and can cause subtle state bugs."

> **code:** an invariant enforced with `assert prefix.startswith("/")` in a
> constructor.
> "using `assert` for a runtime invariant is risky — assertions get stripped under
> `python -O`. should this be an explicit `if ...: raise ValueError(...)`?"

> **code:** a branch checking `if isinstance(e, CancelledError) and not
> isinstance(e, ExceptionGroup):`.
> "the `not isinstance(e, ExceptionGroup)` part looks like it can never be false
> when the first check is true — they're unrelated type hierarchies. is this dead
> code, or am i missing something about how cancellation surfaces here?"
