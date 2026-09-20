# GRPC streaming rules

Detailed entries for `GRPC-009..GRPC-010`. Each follows the four-part
**What / Why / How / When NOT to apply** shape.

---

## GRPC-009 — Choose unary vs streaming honestly; batch instead of fine-grained streams

**What.** Pick the RPC type by the *shape* of the data flow, not fashion:
unary (one request, one response) for a single answer; unary with a
`repeated` field or pagination when you could batch; streaming only for
genuinely continuing, ordered, or huge flows (a live feed, incremental
progress, a multi-GB transfer).

**Why.** Streaming costs on both sides — flow control, cancellation/reconnect
semantics, and testability are all harder — and a stream carrying thousands of
tiny single-field messages pays per-message overhead and forfeits batching,
often running **slower** than one packed message. The wire-level max message
size (4 MiB default, GRPC-017) is an argument for streaming only genuinely
large payloads, not for splitting small ones.

**How.**

```proto
// default: unary — one answer, pageable
rpc ListUsers(ListUsersRequest) returns (ListUsersResponse) {
  // ListUsersResponse { repeated User users = 1; string next_cursor = 2; }
}

// streaming: only when the transport's continuing nature is the point
rpc SubscribeUsers(SubscribeRequest) returns (stream UserEvent);
```

**When NOT to apply.** The mirror-image mistake is forcing a live feed or a
multi-hundred-MB download into unary — that hits the message-size ceiling and
blocks the caller's memory. Use server streaming for large/continuous payloads,
and require a cap/context bound (GRPC-010) when you do.

---

## GRPC-010 — Server streams stop on client cancel; bound work by the stream context

**What.** A streaming handler must stop producing the instant the client
disconnects or cancels: derive all downstream work from `stream.Context()`,
check it in the loop, and return on `Done`. Handle send errors — pushing to a
closed stream returns an error you must unwind from.

**Why.** A vanished client (timeout, navigation, closed laptop) leaves the
server's send blocked or looping. Without ctx checks the server keeps doing the
work behind a half-dead client — a leaked goroutine plus wasted upstream I/O
per abandoned stream. The send error is the observable symptom; bounding the
work by the stream ctx is the fix.

**How.**

```go
func (s *svc) Watch(req *pb.WatchRequest, stream pb.Svc_WatchServer) error {
    for {
        select {
        case <-stream.Context().Done():
            return stream.Context().Err()          // unwind the goroutine
        case ev := <-s.events:
            if err := stream.Send(ev); err != nil {
                return err                          // client gone; stop producing
            }
        }
    }
}
```

Downstream calls inside the handler use `stream.Context()` as their parent so
one cancel propagates through the whole fan-out (GRPC-008 applies to streams
too).

**When NOT to apply.** Buffering a small, *bounded* backlog to absorb short
client gaps is fine (an in-memory queue with a cap). Never block indefinitely
on a slow consumer while ignoring the stream ctx — that is the leak; for
high-throughput fan-out, prefer pub/sub to a long-lived open stream per
consumer.
