"""Exercise run() in a real child process with short, configurable deadlines."""

from dataclasses import FrozenInstanceError
import sys
import time
import unittest

from framework.adapters.python import (
    CosmicSpec,
    Lease,
    PoolOperationError,
    RunnerTransportError,
    RunnerUsageError,
    ScenarioContext,
    run,
)
from tests.fixtures.python_runner_demo import DemoPool, snapshot


FIRST = CosmicSpec("새벽 🚀", "seed", "#123abc", 1)
SECOND = CosmicSpec("Reborn", "star", "#ABCDEF", 2.5)
CHECK = unittest.TestCase()


class ObservedPool(DemoPool):
    def __init__(self, case):
        super().__init__()
        self.case = case
        self.acquired = []
        self.released = []
        self.calls = []

    def acquire(self, spec):
        print("pool acquire")
        self.calls.append("acquire")
        if self.case == "acquire_error":
            raise ValueError("fixture acquire failure")
        if self.case == "null_storage":
            return None
        if self.case == "active_alias" and self.acquired:
            return self.acquired[0]
        obj = super().acquire(spec)
        self.acquired.append(obj)
        return obj

    def release(self, obj):
        self.calls.append("release")
        self.released.append(obj)
        if self.case == "release_error":
            raise ValueError("fixture release failure")
        if self.case == "cleanup_error":
            raise ValueError("fixture cleanup failure")
        super().release(obj)

    def project(self, obj):
        self.calls.append("snapshot")
        if self.case in ("invalid_projection", "cleanup_error"):
            return CosmicSpec("Invalid", "star", "#ffffff", float("nan"))
        if self.case == "mismatched_projection":
            return SECOND
        return snapshot(obj)


def exercise_leases(context, pool):
    invalid_specs = (
        CosmicSpec("🚀" * 21, "seed", "#123abc", 1),
        CosmicSpec("\ufeff", "seed", "#123abc", 1),
        CosmicSpec("\ud800", "seed", "#123abc", 1),
        CosmicSpec("name", "moon", "#123abc", 1),
        CosmicSpec("name", "seed", "#123abc\n", 1),
        CosmicSpec("name", "seed", "#123abc", True),
        CosmicSpec("name", "seed", "#123abc", float("inf")),
        CosmicSpec("name", "seed", "#123abc", 0.29),
        CosmicSpec("name", "seed", "#123abc", 3.51),
    )
    for spec in invalid_specs:
        with CHECK.assertRaises(RunnerUsageError):
            context.acquire(spec)
    CHECK.assertEqual(pool.calls, [])

    first = context.acquire(FIRST)
    CHECK.assertIsInstance(first, Lease)
    historical = context.snapshot(first)
    CHECK.assertEqual(historical, FIRST)
    with CHECK.assertRaises(FrozenInstanceError):
        historical.name = "cannot mutate"
    context.release(first)
    with CHECK.assertRaises(RunnerUsageError):
        context.release(first)

    second = context.acquire(SECOND)
    CHECK.assertIs(pool.acquired[0], pool.released[0])
    CHECK.assertIs(pool.acquired[0], pool.acquired[1])
    CHECK.assertIsNot(first, second)
    CHECK.assertEqual(snapshot(pool.acquired[1]), SECOND)
    CHECK.assertEqual(historical, FIRST)
    CHECK.assertEqual(context.snapshot(second), SECOND)

    for unusable in (first, object(), object.__new__(Lease)):
        with CHECK.assertRaises(RunnerUsageError):
            context.snapshot(unusable)
        with CHECK.assertRaises(RunnerUsageError):
            context.release(unusable)
    CHECK.assertEqual(pool.calls, ["acquire", "snapshot", "release", "acquire", "snapshot"])
    context.release(second)
    CHECK.assertIs(pool.released[0], pool.released[1])
    third = context.acquire(SECOND)
    equal_borrow = context.acquire(SECOND)
    CHECK.assertEqual(context.snapshot(third), context.snapshot(equal_borrow))
    CHECK.assertEqual(pool.acquired[2], pool.acquired[3])
    CHECK.assertIsNot(pool.acquired[2], pool.acquired[3])


def exercise_failure(context, pool, case):
    if case == "active_alias":
        context.acquire(FIRST)
        operation = lambda: context.acquire(SECOND)
    elif case in ("release_error", "release_transport_error"):
        lease = context.acquire(FIRST)
        operation = lambda: context.release(lease)
    else:
        operation = lambda: context.acquire(FIRST)

    error_type = RunnerTransportError if case.endswith("transport_error") else PoolOperationError
    with CHECK.assertRaises(error_type):
        operation()
    calls_at_failure = pool.calls.copy()
    if case == "active_alias":
        CHECK.assertEqual(calls_at_failure, ["acquire", "snapshot", "acquire"])
    if case == "release_transport_error":
        CHECK.assertEqual(calls_at_failure, ["acquire", "snapshot", "release"])
    with CHECK.assertRaises((PoolOperationError, RunnerTransportError, RunnerUsageError)):
        context.acquire(SECOND)
    CHECK.assertEqual(pool.calls, calls_at_failure)
    print("fixture observed fatal error")


def main(case):
    pool = ObservedPool(case)

    def scenario(context):
        print("scenario entered")
        CHECK.assertIsInstance(context, ScenarioContext)
        CHECK.assertEqual(context.participant_id, "runner-tests")
        if case == "leases":
            exercise_leases(context, pool)
        elif case == "keyboard_interrupt":
            raise KeyboardInterrupt
        elif case == "scenario_error":
            context.acquire(FIRST)
            raise RuntimeError("fixture scenario failure")
        elif case == "idle_reply":
            context.acquire(FIRST)
            time.sleep(0.2)
            context.acquire(SECOND)
        elif case == "success":
            context.acquire(FIRST)
            print("final acquire confirmed")
        else:
            exercise_failure(context, pool, case)
        print("fixture assertions passed")

    return run(pool, scenario, snapshot=pool.project, init_timeout=1.5, ack_timeout=0.75)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1]))
