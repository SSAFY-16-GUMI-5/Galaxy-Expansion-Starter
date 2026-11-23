"""Public API for the Python Galaxy Runner."""

from collections.abc import Callable
from contextlib import redirect_stdout
from dataclasses import dataclass
import math
import re
import sys
from time import monotonic
from typing import BinaryIO, Generic, Literal, Protocol, TypeVar

from ._transport import JsonlTransport, MAX_SAFE_INTEGER, RunnerTransportError

__all__ = [
    "CosmicSpec", "Lease", "Pool", "PoolOperationError", "RunnerTransportError",
    "RunnerUsageError", "ScenarioContext", "run",
]

T = TypeVar("T")
MAX_SLOTS = 500
_COLOR = re.compile(r"#[0-9a-fA-F]{6}")
# ECMAScript WhiteSpace and LineTerminator characters used by String.trim().
_TRIM = "\t\n\v\f\r \xa0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"


@dataclass(frozen=True)
class CosmicSpec:
    name: str
    type: Literal["seed", "star", "planet"]
    color: str
    size: float


class Lease:
    """Opaque token identifying one borrow from one Runner session."""

    __slots__ = ()


class Pool(Protocol[T]):
    def acquire(self, spec: CosmicSpec) -> T: ...

    def release(self, obj: T) -> None: ...


class RunnerUsageError(ValueError):
    """Invalid scenario input that can be corrected within the current run."""


class PoolOperationError(RuntimeError):
    """The pool failed or the observed storage violated the Runner contract."""


@dataclass
class _Slot(Generic[T]):
    obj: T
    number: str
    generation: int = 0
    active: bool = False


@dataclass
class _Borrow(Generic[T]):
    lease: Lease
    slot: _Slot[T]
    value: CosmicSpec


def _validated_spec(spec: CosmicSpec) -> CosmicSpec:
    if not isinstance(spec, CosmicSpec):
        raise RunnerUsageError("expected a CosmicSpec")
    name, kind, color, size = spec.name, spec.type, spec.color, spec.size
    if not isinstance(name, str) or not name.strip(_TRIM):
        raise RunnerUsageError("name must contain a non-whitespace character")
    try:
        name.encode("utf-8")
        name_units = len(name.encode("utf-16-le")) // 2
    except UnicodeError as exc:
        raise RunnerUsageError("name must be valid UTF-8") from exc
    if name_units > 40:
        raise RunnerUsageError("name must fit in 40 UTF-16 code units")
    if not isinstance(kind, str) or kind not in ("seed", "star", "planet"):
        raise RunnerUsageError("type must be seed, star or planet")
    if not isinstance(color, str) or not _COLOR.fullmatch(color):
        raise RunnerUsageError("color must be #RRGGBB")
    if type(size) not in (int, float) or not 0.3 <= size <= 3.5:
        raise RunnerUsageError("size must be a finite number between 0.3 and 3.5")
    return CosmicSpec(name, kind, color, size)


class ScenarioContext(Generic[T]):
    """Synchronous access to the session's tracked borrows."""

    def __init__(
        self,
        participant_id: str,
        pool: Pool[T],
        snapshot: Callable[[T], CosmicSpec],
        transport: JsonlTransport,
        ack_timeout: float,
    ):
        self._participant_id = participant_id
        self._pool = pool
        self._project = snapshot
        self._transport = transport
        self._ack_timeout = ack_timeout
        self._slots: dict[int, _Slot[T]] = {}
        self._borrows: dict[int, _Borrow[T]] = {}
        self._failure: Exception | KeyboardInterrupt | None = None
        self._closed = False

    @property
    def participant_id(self) -> str:
        return self._participant_id

    def _require_live(self) -> None:
        if self._failure is not None:
            raise self._failure
        if self._closed:
            raise RunnerUsageError("session is closed")

    def _require_borrow(self, lease: Lease) -> _Borrow[T]:
        borrow = self._borrows.get(id(lease))
        if borrow is None or borrow.lease is not lease:
            raise RunnerUsageError("lease is not active in this session")
        return borrow

    def acquire(self, spec: CosmicSpec) -> Lease:
        self._require_live()
        requested = _validated_spec(spec)
        try:
            self._transport.check_idle(sending=True)
            try:
                obj = self._pool.acquire(spec)
            except (Exception, SystemExit) as exc:
                raise PoolOperationError(f"acquire: pool.acquire failed: {exc}") from exc
            if obj is None:
                raise PoolOperationError("acquire: pool returned no storage")

            # The slots retain strong references, so a recorded id cannot be reused.
            identity = id(obj)
            slot = self._slots.get(identity)
            if slot is not None and slot.active:
                raise PoolOperationError(f"acquire: pool returned active slot {slot.number}")

            try:
                if slot is None:
                    if len(self._slots) >= MAX_SLOTS:
                        raise PoolOperationError("acquire: 500 observed slots already allocated")
                    slot = _Slot(obj, str(len(self._slots) + 1))
                if slot.generation >= MAX_SAFE_INTEGER:
                    raise PoolOperationError(f"acquire: generation limit for slot {slot.number}")
                try:
                    value = _validated_spec(self._project(obj))
                except (Exception, SystemExit) as exc:
                    raise PoolOperationError(f"acquire: invalid pool snapshot: {exc}") from exc
                if value != requested:
                    raise PoolOperationError("acquire: pool snapshot differs from requested spec")
            except PoolOperationError:
                # This storage is a new borrow and has not been published.
                try:
                    self._pool.release(obj)
                except (Exception, SystemExit):
                    pass
                raise

            self._slots[identity] = slot
            slot.generation += 1
            slot.active = True
            self._transport.exchange(
                {
                    "type": "acquire",
                    "poolSlotId": slot.number,
                    "generation": slot.generation,
                    "data": {
                        "name": value.name,
                        "type": value.type,
                        "color": value.color,
                        "size": value.size,
                    },
                },
                self._ack_timeout,
            )
            lease = Lease()
            self._borrows[id(lease)] = _Borrow(lease, slot, value)
            return lease
        except (PoolOperationError, RunnerTransportError, KeyboardInterrupt) as exc:
            self._failure = exc
            raise

    def snapshot(self, lease: Lease) -> CosmicSpec:
        self._require_live()
        borrow = self._require_borrow(lease)
        try:
            self._transport.check_idle()
        except RunnerTransportError as exc:
            self._failure = exc
            raise
        return borrow.value

    def release(self, lease: Lease) -> None:
        self._require_live()
        borrow = self._require_borrow(lease)
        slot = borrow.slot
        try:
            self._transport.check_idle(sending=True)
            try:
                self._pool.release(slot.obj)
            except (Exception, SystemExit) as exc:
                raise PoolOperationError(
                    f"release slot {slot.number} generation {slot.generation}: "
                    f"pool.release failed: {exc}"
                ) from exc
            del self._borrows[id(lease)]
            slot.active = False
            self._transport.exchange(
                {"type": "release", "poolSlotId": slot.number, "generation": slot.generation},
                self._ack_timeout,
            )
        except (PoolOperationError, RunnerTransportError, KeyboardInterrupt) as exc:
            self._failure = exc
            raise


def _run(
    output: BinaryIO,
    pool: Pool[T],
    scenario: Callable[[ScenarioContext], None],
    *,
    snapshot: Callable[[T], CosmicSpec],
    reset_on_start: bool = False,
    init_timeout: float = 5.0,
    ack_timeout: float = 2.0,
) -> int:
    transport = None
    context = None
    phase = "init"
    try:
        for timeout in (init_timeout, ack_timeout):
            if not math.isfinite(timeout) or timeout < 0:
                raise RunnerTransportError("timeouts must be finite and nonnegative")
        deadline = monotonic() + init_timeout
        transport = JsonlTransport(sys.stdin.fileno(), output)
        participant_id = transport.read_init(deadline)
        if reset_on_start:
            phase = "startup reset"
            transport.exchange({"type": "reset"}, ack_timeout)
        phase = "scenario"
        context = ScenarioContext(participant_id, pool, snapshot, transport, ack_timeout)
        try:
            scenario(context)
        finally:
            # Participant code can catch a fatal error, but cannot recover the session.
            context._require_live()
        transport.check_idle()
        return 0
    except KeyboardInterrupt:
        print(f"[galaxy runner] {phase}: interrupted", file=sys.stderr)
        return 130
    except (Exception, SystemExit) as exc:
        print(f"[galaxy runner] {phase}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        if context is not None:
            context._closed = True
        if transport is not None:
            transport.close()


def run(
    pool: Pool[T],
    scenario: Callable[[ScenarioContext], None],
    *,
    snapshot: Callable[[T], CosmicSpec],
    reset_on_start: bool = False,
    init_timeout: float = 5.0,
    ack_timeout: float = 2.0,
) -> int:
    """Run a pool-backed scenario using the current process streams."""
    try:
        output = sys.stdout.buffer
    except AttributeError as exc:
        print(f"[galaxy runner] init: cannot access binary stdout: {exc}", file=sys.stderr)
        return 1
    with redirect_stdout(sys.stderr):
        return _run(
            output, pool, scenario, snapshot=snapshot, reset_on_start=reset_on_start,
            init_timeout=init_timeout, ack_timeout=ack_timeout,
        )
