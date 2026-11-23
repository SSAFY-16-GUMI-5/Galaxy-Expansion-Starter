# Galaxy Runner contract

This is the in-process API for the Python MVP. [Galaxy Protocol v1](PROTOCOL.md) defines the wire contract. See [Runner architecture](RUNNER_ARCHITECTURE.md) for component responsibilities and rollout.

## Python MVP API

The following signatures describe the API surface. `CosmicSpec` is a frozen data class. `Lease` is opaque and constructed by the Runner. Participant-specific signatures can be adapted at the application entry point.

```python
@dataclass(frozen=True)
class CosmicSpec:
    name: str
    type: Literal["seed", "star", "planet"]
    color: str
    size: float

class Pool(Protocol[T]):
    def acquire(self, spec: CosmicSpec) -> T: ...
    def release(self, obj: T) -> None: ...

class ScenarioContext:
    @property
    def participant_id(self) -> str: ...
    def acquire(self, spec: CosmicSpec) -> Lease: ...
    def snapshot(self, lease: Lease) -> CosmicSpec: ...
    def release(self, lease: Lease) -> None: ...

def run(
    pool: Pool[T],
    scenario: Callable[[ScenarioContext], None],
    *,
    snapshot: Callable[[T], CosmicSpec],
    reset_on_start: bool = False,
    init_timeout: float = 5.0,
    ack_timeout: float = 2.0,
) -> int: ...
```

`run` uses the process streams. The entry point calls `raise SystemExit(run(pool, scenario, snapshot=read_cosmic_object))`. `snapshot` is a participant-supplied, read-only projection of the actual object's four public fields. The context returns the immutable snapshot captured at acquire for a currently active lease. The pool owns the mutable object throughout. The scenario receives the context alone and drives it synchronously on the calling thread. One run owns stdout and each pool starts without outstanding borrows.

## Operation rules

| Operation | Required behavior |
| --- | --- |
| Acquire | Validate the requested spec before calling the pool. Call `pool.acquire(spec)` once. Require a valid non-null storage instance whose identity is inactive or new. Capture and validate its snapshot and require that it matches the requested fields. Publish the acquire with the Runner-derived slot and generation. Return the fresh lease only after the acquire ack. |
| Snapshot | Require the exact active lease issued by this session and return its captured value snapshot. A previously obtained value snapshot remains valid as historical data after the lease ends. |
| Release | Require the exact active lease issued by this session. Call `pool.release(obj)` once for that borrow. On local success invalidate the lease, publish the release with its existing slot and generation, and wait for the release ack before returning. |
| Optional startup reset | After init and before scenario code, publish `reset` and wait for its ack. The session starts with an empty ledger and fresh lease identities. Scenarios have no reset operation. |

The first observed identity gets a fresh string slot ID (for example, `"1"`) and generation 1. Any later acquisition of that same storage after a successful release uses the same slot with generation incremented by exactly one. Equality between instances does not determine identity. An acquire that returns an already borrowed instance is a pool contract violation, even if its fields changed. Keep all previously observed identity records until termination. Local capacity belongs to the participant pool. The Runner also enforces v1's limit of 500 observed slots per run and positive safe-integer generations up to 9,007,199,254,740,991. It must fail before emitting an event that would exceed either bound.

## Validation and errors

- For acquire input and projection, require a string `name` of at most 40 UTF-16 code units with at least one non-whitespace character after ECMAScript `trim` semantics, matching the existing JavaScript checks. Require valid UTF-8 encodability of the input name, exact `type`, a full `#RRGGBB` hex match, and finite numeric `size` within `[0.3, 3.5]`. Accept Python `int` or `float` for `size`, excluding `bool`. Preserve the spelling in the wire snapshot. The Relay trims the published display name.
- Raise `RunnerUsageError` for invalid request data or a foreign, stale, fabricated or already released lease. This leaves the ledger and transport untouched, and a scenario that handles the exception may continue. Compare leases by issuance identity, including session ownership, so an old lease cannot release a re-borrowed object.
- Raise `PoolOperationError` for domain exceptions, invalid projections, an already active acquire result or a Runner slot/generation limit reached after observing a borrow. This aborts the session. Pool methods that raise should leave their domain state unchanged. For a failed acquire before publication, the Runner may make one best-effort release only if the result is known to be a new borrow and its storage is not already active. Preserve the original failure if local cleanup fails. An invalid acquire that aliases an active object must never cause the Runner to return that object on the caller's behalf.
- Raise `RunnerTransportError` for malformed control input, invalid or unexpected replies, explicit remote rejection, timeouts or pipe failures. Any such failure poisons the session. After local mutation, remote rejection or a lost reply may leave local and remote states different. Stop sending events, log the phase and current event context, and exit nonzero. The Runner never retries uncertain events or sends compensating events. A caught fatal error still prevents further operations and a zero exit.
- `run` returns `0` on scenario completion and receipt of all expected acks, `1` on handshake, domain, scenario or transport failure, and `130` for a handled keyboard interrupt. Diagnostics go to stderr. A scenario exception ends the run without automatic network cleanup.

## JSONL transport

1. Read exactly one UTF-8 JSON object on stdin before invoking the scenario or calling pool methods. Require `type: "init"` and a string `participantId` matching `[A-Za-z0-9_-]{1,32}`. Accept LF and CRLF. Invalid UTF-8, malformed JSON, EOF or expiration of the init deadline fails startup.
2. Emit only `acquire`, `release` or an explicitly enabled startup `reset` to stdout, using the exact v1 field names. Always write slot IDs as strings. Omit `participantId`, lease information and extra fields. Serialize strict JSON, using UTF-8 without a BOM and LF terminators. Check that the encoded payload before the newline fits 8,000 bytes. Write and flush each complete line before waiting for a reply. Scenario and pool diagnostics go to stderr.
3. Read one reply within the per-event deadline. Require `ack.action` to match the outstanding event and `revision` to be a positive safe integer. Revisions may skip values because the Relay shares them across participants. An `error` object with a string `message` is a rejection of the sole pending event and fails the run. An unsolicited reply while idle or a second `init` is a control-stream error. A timeout, EOF or interrupted write before confirmation makes delivery uncertain.
4. Exit after the scenario returns and the final event is confirmed. Do not wait for EOF or implicitly publish releases or a reset at shutdown. Treat broken pipes as failures and avoid printing machine status to stdout.

On Python, use binary process streams with explicit UTF-8 encode/decode and `json.dumps(..., ensure_ascii=False, allow_nan=False)`. Reject non-JSON constants on input. For cross-platform init and reply deadlines, use one dedicated stdin reader thread with a bounded queue or equivalent, and have the main thread wait using monotonic deadlines. A blocked reader must not hold process exit open. EOF and reader failures should be delivered to the waiting caller. Avoid polling a buffered stdin with socket-only readiness APIs on Windows.

## Acceptance cases

| Boundary | Minimum cases |
| --- | --- |
| Pool and tracker | Use a deterministic single-storage test double to verify real identity reuse, generation 1 → 2 and fresh snapshots. Distinct equal-valued instances get different slots. Test a stale lease after re-acquire, foreign lease, duplicate return, active alias, invalid input/projection, and thrown pool operation. Assert call order and zero events for rejected local calls. Participant tests separately demonstrate reuse in the real domain. |
| JSONL subprocess | Cover valid init, UTF-8 including a non-ASCII name, mismatched ack action, explicit rejection, malformed or oversized data, timeout, early EOF, final ack before successful exit, and optional startup reset before the first borrow. Assert no following event after a protocol failure. |
| Existing hosts | Run `node scripts/verify-protocol.mjs -- python -m framework.adapters.python --module solution.main` from Starter with a completed finite scenario. With the Platform Relay running, use the same Python command after `node ../Galaxy-Expansion/bridge/local-bridge.mjs --` from Starter. Confirm expected generations and visible active stars. Repeat under the same participant ID with explicit startup reset to verify the restart path. |

Complete the TODOs in `solution/main.py` and launch the Runner via `python -m framework.adapters.python --module solution.main` from Starter. For a ready-to-run fixture, use `--module tests.fixtures.python_runner_demo`. The existing Starter `npm test` and `npm run verify:fixture` validate the baseline contract independently of a Runner implementation.
