---
name: grpc-best-practices
description: Use when working with gRPC — .proto files and proto3 schema design, enum zero values and _UNSPECIFIED sentinels, well-known types (google.protobuf.Timestamp / Duration / FieldMask), List pagination (page_size / page_token / next_page_token), buf or protoc generation, grpc-go / grpclib / grpcio servers and clients, google.rpc status codes and rich errors, deadlines and cancellation propagation, streaming RPCs (server/client/bidi), interceptors (auth, logging, panic recovery, protovalidate), TLS / mTLS transport credentials and the insecure-credentials footgun, server reflection + grpcurl/grpcui, health checking, message-size limits and connection reuse. Covers the GRPC- rule family (proto design, error model, deadlines, streaming, interceptors, security, tooling, performance). Protocol-level rules apply to any language; code examples are grpc-go. For the language underneath, see go-best-practices.
---

# gRPC best practices

A curated rule set for designing and operating gRPC APIs. Each rule
has a stable ID and a one-line summary. Full **What / Why / How /
When-not-to-apply** entries live in `references/`.

Protocol-level rules apply to any gRPC implementation; code examples
are grpc-go. Language-level Go concerns (errors, contexts, tooling)
live in [`go-best-practices`](../go-best-practices/SKILL.md);
container packaging lives in
[`containers-best-practices`](../containers-best-practices/SKILL.md).

## When to apply this skill

Activate when any of these are true:

- A `.proto` file, `buf.yaml`, `buf.gen.yaml`, or generated `*.pb.go` / gRPC stub file is in context.
- The user is building or reviewing a gRPC service or client: service/message definitions, status codes, deadlines, streaming, interceptors, health checks, or reflection.
- The user mentions gRPC tooling: `buf`, `protoc`, `grpcurl`, `grpcui`, `grpc-health-probe`, protovalidate.
- The user references a `GRPC-` rule ID.

## How to use the rule index

1. Scan the relevant section(s) below for rule IDs that apply to the current file.
2. For each rule you intend to apply or flag, open the corresponding `references/` file and read **only that rule's entry** — they're keyed by ID.
3. Cite the rule ID when you explain a change to the user.

## Rules — Proto design

See [`references/proto-design.md`](./references/proto-design.md).

- **GRPC-001** — Field numbers are permanent: evolve proto3 additively; never renumber, repurpose, or change a field's type.
- **GRPC-002** — Distinguish "unset" from zero with proto3 `optional` (or wrappers); proto3 has no `required`.
- **GRPC-003** — Dedicated `XxxRequest`/`XxxResponse` pair per RPC; messages are nouns, RPCs are verb+noun.
- **GRPC-019** — Reserve enum `0` for a `_UNSPECIFIED` sentinel; never put a real value there.
- **GRPC-020** — Model time with `google.protobuf.Timestamp`/`Duration`, not raw `int64` or strings.
- **GRPC-021** — Paginate unbounded `List` RPCs with `page_size`/`page_token`/`next_page_token`.

## Rules — Error model

See [`references/error-model.md`](./references/error-model.md).

- **GRPC-004** — Return canonical `google.rpc.Code` values mapped from your domain; never invent codes or leak HTTP/transport assumptions.
- **GRPC-005** — Add machine-readable detail (`google.rpc.ErrorInfo` via `status.WithDetails`) so clients branch on data, not message strings.
- **GRPC-006** — Translate internal errors to gRPC status only at the service boundary; log the cause, return generic `INTERNAL` for unknown failures.

## Rules — Deadlines

See [`references/deadlines.md`](./references/deadlines.md).

- **GRPC-007** — Clients set a deadline on every RPC (`context.WithTimeout`); a deadline-free call can hang a goroutine and cascade.
- **GRPC-008** — Handlers honor the context: check `ctx.Err()`, propagate ctx downstream, return on the deadline budget instead of continuing zombie work.

## Rules — Streaming

See [`references/streaming.md`](./references/streaming.md).

- **GRPC-009** — Choose unary vs streaming honestly: a `repeated` field in one message beats a stream of thousands of tiny messages.
- **GRPC-010** — Server streams must stop on client cancel: bound work by `stream.Context()`, handle send errors, return on `Done`.

## Rules — Interceptors

See [`references/interceptors.md`](./references/interceptors.md).

- **GRPC-011** — Cross-cutting concerns (auth, logging, recovery, validation) live in interceptors, composed with deliberate ordering.
- **GRPC-012** — Recover panics in a server interceptor (grpc-go has none built in) so one bad handler can't crash the process.
- **GRPC-013** — Validate with `buf.validate` + a protovalidate interceptor; return `INVALID_ARGUMENT`, not hand-rolled per-handler checks.

## Rules — Security

See [`references/security.md`](./references/security.md).

- **GRPC-018** — Run production gRPC over TLS; `insecure.NewCredentials()` is dev-only.

## Rules — Tooling

See [`references/tooling.md`](./references/tooling.md).

- **GRPC-014** — Manage schemas with `buf`; gate CI on `buf lint` + `buf breaking --against`; keep generated code in sync.
- **GRPC-015** — Enable server reflection in dev for grpcurl/grpcui; wire health checking (`grpc.health.v1`) for production probes.

## Rules — Performance

See [`references/performance.md`](./references/performance.md).

- **GRPC-016** — Reuse one client connection per backend process (HTTP/2 multiplexes); never dial per call; set keepalive.
- **GRPC-017** — Set `MaxRecvMsgSize`/`MaxSendMsgSize` deliberately; the 4 MiB default fails loudly — stream or batch instead of unbounded limits.
