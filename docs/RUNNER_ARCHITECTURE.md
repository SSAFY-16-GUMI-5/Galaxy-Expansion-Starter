# Galaxy Runner architecture

The Runner is a local adapter for the Object Pooling assignment. It calls participant code in the same process, observes successful borrows and returns, and sends their events through the existing [Galaxy Protocol v1](PROTOCOL.md). The Python MVP leaves `CosmicObject`, storage allocation, reuse policy, reinitialization and the pool's own lifecycle checks in `solution/`.

```text
Participant scenario
  → Runner session and tracked leases
    → Participant ObjectPool (same process)
    → UTF-8 JSONL transport (stdin/stdout)
      ↔ Starter verifier OR Platform Local Bridge
        ↔ Relay → read-only WebGL viewer
```

| Layer | Owns |
| --- | --- |
| Participant domain | Actual objects or storage, pool capacity, selection of available storage, and initialization and return semantics |
| Scenario | The order and inputs of acquire/release operations and any presentation delays |
| Runner session | Lease validity, observed identity → wire-slot mapping, generation, snapshots, validation and failure state |
| JSONL adapter | Handshake, framing, serialized writes, acknowledgment matching, deadlines and stderr diagnostics |
| Bridge and Relay | Connection and authentication, remote validation and state, and distribution to viewers |

The public API and wire behavior are specified in [Runner contract](RUNNER_CONTRACT.md).

## Where events come from

Each tracked operation invokes a real domain operation. Acquire observes the returned storage identity and captures a value snapshot of the initialized object. Release uses the exact storage borrowed by the current lease. The Runner derives slot and generation from those observations. There is no public event-emission method and a scenario supplies neither slot IDs nor generations.

The Runner gives each newly observed storage identity a session-local slot ID. It keeps an identity record for inactive slots as well as active slots. Python, Java, and C# key on reference identity. C++ keys on stable storage addresses. Rust binds a borrow handle to a stable storage token that identifies an actual pool slot. Each adapter distinguishes storage identity from the identity of an individual borrow.

The underlying storage identity and the lease identity have different lifetimes. A new lease is issued each time an object is acquired. A return invalidates that lease even if the same object is active again under a new lease. The scenario receives an opaque lease and immutable snapshots. The participant still tests its pool directly by comparing storage identity, checking reinitialization and exercising its own misuse handling.

Run one fresh pool and one scenario serially per process invocation. The scenario uses the tracked API for all pool operations. The pool and scenario are trusted local code. The Runner provides lifecycle checks at its API boundary, while in-process code has the permissions of the local Runner process. The only objects sent across the transport are v1 JSON data.

## Confirmation and pacing

The MVP uses one outstanding event and waits for its `ack` or `error` before it continues. v1 `ack` includes `action` and `revision`, and `error` supplies a message. With one outstanding event, the Runner can associate a reply without inventing request IDs or inferring a revision from its event count. A successful write means the line reached the local pipe. The matching reply means the verifier accepted the transcript step or the Relay applied the event, depending on which parent launched the Runner. The Relay sends its ack before publishing to viewers, so display timing is independent.

Use an event-send interval of at least 25 ms in the MVP, measured with a monotonic clock. Acknowledgments alone can return fast enough to hit the Relay's 90 messages/second limit, which also counts connection messages. Optional longer scenario delays make visualization easier. Keep verifier scenarios finite and fit their delays, execution and acknowledgments into the verifier's default 15-second process timeout. The verifier can be configured through `GALAXY_VERIFY_TIMEOUT_MS` (1–60 seconds) and allows up to 2,000 stdout lines.

The Bridge sends `init` after authenticating and starting the child, forwards Relay `ack`/`error`, and closes the socket on child exit. Waiting through the final ack avoids exiting while the Bridge still has a last event to forward. When the child exits nonzero, the present Bridge logs the child exit code. Inspect that diagnostic when running through the Bridge.

## Starting and ending a run

Use a fresh participant namespace for a normal live run. The Relay retains participant slots on disconnect and the v1 `init` contains no state snapshot. For an intentional restart under the same participant ID, opt in to a startup `reset` and wait for its ack before starting the scenario. This clears the authenticated participant's remote state. The Runner begins with an empty identity ledger and the pool must start with no outstanding borrows. A restart after uncertain delivery requires an explicit operator decision to use a fresh ID or clear the prior state.

A scenario may finish with active display objects. Successful termination waits for the final ack, exits without waiting for stdin EOF, and lets process exit reclaim local pool storage. A scenario that requires its stars removed explicitly releases them before returning. A remote error or transport ambiguity ends the run because a successful domain operation and its remote event cannot be committed atomically across this transport. Automatic retrial, rollback of published state, and reconnect/replay are outside the MVP.

## Compatibility and implementation order

Existing v1 participant executables continue to run directly under the verifier or Bridge. The Runner is an optional local entry point. Python, C++, Java, C#, and Rust implement the same synchronous domain adapter, lease lifecycle and finite scenario model using their native ownership mechanisms. Build and launch commands are in the [language guide](LANGUAGE_GUIDE.md).

1. Build the tracked API and test it against a single-storage test double. Keep participants' pool implementations in their solutions.
2. Implement the stdin/stdout adapter and exercise success, rejection, stalled replies and exit using subprocess fixtures.
3. Run the unchanged Starter verifier against a finite Runner scenario that acquires, releases and re-acquires the same storage. Then run the scenario through the Local Bridge and a local Relay to confirm the viewer state.

The verifier exercises ordering, validation and transcript reuse. Language-level tests establish actual storage reuse and reinitialization. The Bridge smoke test adds authentication, Relay state and the final acknowledgment path.
