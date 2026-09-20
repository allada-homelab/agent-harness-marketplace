# GRPC proto-design rules

Detailed entries for `GRPC-001..GRPC-003` and `GRPC-019..GRPC-021`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-001 — Field numbers are permanent: evolve proto3 additively; never renumber or repurpose

**What.** A published `.proto` is append-only. Field numbers and names are the
wire contract: add new fields with new numbers, keep old numbers meaning
exactly what they always meant, never delete-and-reuse a number or change a
field's type. Flag removed numbers with `reserved`.

**Why.** A consumer built against schema *v1* unmarshals your *v2* messages
using the field numbers it compiled against. If field 5 becomes a `string` when
it was an `int32`, the consumer decodes garbage (drivers interpret wrong-typed
fields per wire rules — silently, as zero or truncated); if you reuse a removed
number for a different field, old clients see the new field under the old
semantics — the worst kind of compat break because it does not error. Because
field-name changes shift JSON names (transcoding/gRPC-Gateway), renaming is
also a compat break for gateways, not just for binaries.

**How.**

```proto
message User {
  int64  id    = 1;   // permanent — never repurpose
  string name  = 2;   // permanent
  // reserved 3, 5;   // optional: block reuse of removed numbers
  string email = 4;   // new field gets the next free number
}
```

Enforce mechanically: `buf lint` + `buf breaking` in CI (see GRPC-014) catch
renumbering and type changes before they ship.

**When NOT to apply.** Pre-1.0, explicitly-marked unstable APIs are the usual
carve-out — but the discipline still pays, because consumers ship ahead of your
next iteration. If you truly need a large breaking change, version the API (a
separate package or `user.v2.User`), don't mutate fields.

---

## GRPC-002 — Distinguish "unset" from zero with proto3 `optional` (or wrappers)

**What.** proto3 scalars have no presence: a `0`, `""`, `false` value and an
omitted value look identical on the wire. When absence is a real state — "no
email set" vs empty string, "no limit given" vs `limit: 0` — declare the field
`optional` (`optional int32 limit = 2;`) or use a wrapper/message type
(`google.protobuf.Int32Value`, `google.protobuf.StringValue`).

**Why.** Services that treat absent and zero as one produce wrong behavior
silently: a client omitting `limit` expecting the server default scans "0
rows"; an absent enum reads as `UNKNOWN` and code branches wrongly. Once the
ambiguity ships, callers can't recover without a breaking change — presence
has to be in the schema from the first version.

**How.**

```proto
message ListUsersRequest {
  optional int32 limit = 2;   // nil = "use server default"
  optional string cursor = 3; // nil = "start at beginning"
}
```

In generated Go protobuf code (protoc-gen-go) an `optional` field is a pointer (`*int32`): check
`if req.Limit != nil { ... }` — a nil pointer is the encoded absence.

**When NOT to apply.** If your domain genuinely has no meaningful "absent"
state (a count that is always set), a plain scalar is simpler and correct.
Wrappers cost an allocation per message, so don't wrap every field habitually —
only where absence changes behavior.

---

## GRPC-003 — Dedicated `XxxRequest`/`XxxResponse` pair per RPC; messages are nouns, RPCs are verb+noun

**What.** Give each RPC its own request and response message
(`GetUserRequest`/`GetUserResponse`) even when two RPCs currently share a
shape. Name messages as nouns and RPCs as `verb + noun`
(`GetUser`, `ListUsers`). Keep message names package-scoped to avoid collisions.

**Why.** A shared message freezes two RPCs' evolution together: adding a field
for RPC *A* forces it onto RPC *B*'s wire, and deleting a field ships the
breakage to both consumers at once. The gRPC contract is the exchange — a
dedicated pair is the standard handshake that keeps each RPC evolvable
independently (and is what the gRPC core documentation recommends).

**How.**

```proto
service Users {
  rpc GetUser(GetUserRequest) returns (GetUserResponse);
  rpc ListUsers(ListUsersRequest) returns (ListUsersResponse);
}

message GetUserRequest  { string user_id = 1; }
message GetUserResponse { User user = 1; }
```

**When NOT to apply.** Throwaway echo/health scaffolding may reuse a generic
pair, but any RPC that will evolve deserves its own. Requests and responses in
a *pair* sharing a body (request carries input fields; response carries the
payload) is normal — the pair is the unit, not the individual message.

---

## GRPC-019 — Reserve enum `0` for a `_UNSPECIFIED` sentinel; never put a real value there

**What.** proto3 requires an enum's first value to be `0`, and an unset enum
field decodes as `0`. So `0` must be a sentinel meaning "not set" —
`ENUM_NAME_UNSPECIFIED = 0` — never a meaningful member. Prefix every value
name with the enum name.

**Why.** This is GRPC-002's presence problem in enum form. Put
`STATUS_ACTIVE = 0` in and "the caller never set status" and "the caller chose
ACTIVE" are the same bytes — proto3 doesn't even serialize a singular field
holding its default, so the field is absent on the wire either way. Every
consumer inherits a default it cannot opt out of: an update marks dormant rows
active, a filter meaning "any status" silently narrows to one. Fixing it later
means renumbering — a GRPC-001 breaking change. Two of buf's `STANDARD` lint
rules exist for exactly this: `ENUM_ZERO_VALUE_SUFFIX` (the zero value must end
in `_UNSPECIFIED`; the suffix is configurable) and `ENUM_VALUE_PREFIX` (value
names carry the enum's name, because enum values are siblings of the enum in
the enclosing scope under C++ scoping rules — two enums in a package cannot
share a value name). GRPC-014's CI gate catches both mechanically.

**How.**

```proto
enum OrderStatus {
  ORDER_STATUS_UNSPECIFIED = 0;   // sentinel: caller sent nothing
  ORDER_STATUS_PENDING     = 1;
  ORDER_STATUS_SHIPPED     = 2;
  ORDER_STATUS_CANCELLED   = 3;
}

message UpdateOrderRequest {
  string      order_id = 1;
  OrderStatus status   = 2;   // UNSPECIFIED = leave unchanged
}
```

Handle the sentinel explicitly — `if req.GetStatus() ==
pb.OrderStatus_ORDER_STATUS_UNSPECIFIED { ... }` — rather than letting it fall
through a `switch` into whatever the first case happens to do.

**When NOT to apply.** Effectively never for a published schema. The only
shape that argues against it is an enum whose zero value genuinely is the
correct universal default *and* where absence never needs distinguishing — and
that holds far less often than it feels like, because it has to stay true for
every future consumer, not just today's. buf lets you configure the suffix if
your house style differs; the default is the right one. Note this is about
*unset*, not *unknown*: open enums (Go, C++) already preserve unrecognized
non-zero values received from newer peers.

---

## GRPC-020 — Model time with `google.protobuf.Timestamp`/`Duration`, not raw `int64` or strings

**What.** An instant is `google.protobuf.Timestamp`; a span is
`google.protobuf.Duration`; the set of fields a partial update touches is
`google.protobuf.FieldMask`. Import these from `google/protobuf/*.proto`
instead of inventing `int64 created_at` or `string expires_in`.

**Why.** `int64 created_at` carries no unit — seconds or milliseconds is a
comment at best, and the classic cross-team integration bug is one side writing
millis into a field the other reads as seconds. Dates land in 1970 or the year
53000 and nothing errors, because both are valid int64s; there's no timezone
semantics either, so "is this UTC?" becomes tribal knowledge. Strings are
worse: every service invents its own parse. The well-known types put the unit
in the type (seconds + nanos since the UTC epoch) and come with generated
helpers instead of hand-rolled conversion — in Go, `timestamppb.New(t)` and
`ts.AsTime()` from `google.golang.org/protobuf/types/known/timestamppb`, and
`durationpb.New` / `AsDuration` for spans. They also fix the JSON: protobuf's
canonical mapping renders `Timestamp` as RFC 3339 (`2026-08-16T01:30:15.010Z`)
and `Duration` as a seconds string (`"3.000000001s"`), so a transcoding gateway
or a JS client gets something parseable rather than a number of unclear scale.

**How.**

```proto
import "google/protobuf/duration.proto";
import "google/protobuf/field_mask.proto";
import "google/protobuf/timestamp.proto";

message Session {
  string                    id         = 1;
  google.protobuf.Timestamp created_at = 2;
  google.protobuf.Duration  ttl        = 3;
}

message UpdateSessionRequest {
  Session                   session     = 1;
  google.protobuf.FieldMask update_mask = 2;   // which fields to write
}
```

```go
s.CreatedAt = timestamppb.New(time.Now().UTC())
created := s.GetCreatedAt().AsTime()
```

**When NOT to apply.** An existing wire contract already speaking epoch ints is
a real reason not to churn — add the well-known type as a *new* field and
deprecate the old one rather than changing a field's type (GRPC-001). And a
`Timestamp` is a nested message: an extra tag, a length prefix and two nested
fields, against a single scalar field for a bare `int64`. On a hot path
shipping millions of tiny messages that can matter — but measure it on your
own payloads before trading the ambiguity back.

---

## GRPC-021 — Paginate unbounded `List` RPCs with `page_size`/`page_token`/`next_page_token`

**What.** Any List RPC over a collection that can grow takes `int32 page_size`
and `string page_token` in its request and returns `string next_page_token` in
its response — the AIP-158 shape. An empty `next_page_token` is the *only*
signal that the collection is exhausted. Tokens are opaque cursors the server
mints and the client echoes back verbatim, never user-parseable offsets.

**Why.** An unpaginated List works right up until the table grows, then trips
the receiver's 4 MiB message cap (GRPC-017) and fails in production on a
payload shape no test produced — and retrofitting pagination at that point is a
breaking change for every existing caller, at the worst possible moment. Offset
pagination isn't the fix either: `LIMIT n OFFSET k` re-scans k rows on every
page, so page 500 costs 500 pages of work, and any insert or delete between
requests shifts the window — callers silently skip rows or see them twice. An
opaque cursor encodes the server's real position (a sort key, a resume token),
so it stays correct under concurrent writes and stays O(page). Opaque also
means you can change that encoding later without breaking clients who never
parsed it.

**How.**

```proto
message ListOrdersRequest {
  string customer_id = 1;
  int32  page_size   = 2;   // 0 = server default; server clamps to its own max
  string page_token  = 3;   // empty = first page
}

message ListOrdersResponse {
  repeated Order orders          = 1;
  string         next_page_token = 2;   // empty = end of collection
}
```

A dedicated request/response pair per RPC, per GRPC-003 — pagination fields are
exactly what leaks across RPCs when messages are shared. The server clamps
`page_size` against a maximum of its own; treating the client's number as
authoritative just moves the unbounded-response bug up one level.

**When NOT to apply.** Collections bounded by construction — one entry per enum
member, a user's handful of API keys — don't need it; a `repeated` field in one
response is simpler and is what GRPC-009 recommends. And pagination is for
client-driven paging, not continuous feeds: when the client wants everything as
fast as the server can produce it, server streaming (GRPC-009/010) is the right
tool.
