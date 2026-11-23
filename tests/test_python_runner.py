"""Public API and JSONL subprocess tests for the Python Runner."""

from io import BytesIO, TextIOWrapper
import json
import os
from pathlib import Path
from queue import Empty, Queue
import re
import subprocess
import sys
from threading import Thread
import unittest
from unittest.mock import patch

from framework.adapters.python import CosmicSpec, RunnerUsageError, run
from tests.fixtures.python_runner_demo import create_pool, snapshot


ROOT = Path(__file__).resolve().parents[1]
INIT = {"type": "init", "participantId": "runner-tests"}
DEMO = "tests.fixtures.python_runner_demo"


class DemoPoolTests(unittest.TestCase):
    def test_reborrowing_reinitializes_the_same_object(self):
        pool = create_pool()
        first = CosmicSpec("Original", "seed", "#123abc", 0.8)
        second = CosmicSpec("Reborn", "star", "#F4BD64", 1.6)
        obj = pool.acquire(first)
        historical = snapshot(obj)
        self.assertEqual(historical, first)
        pool.release(obj)
        with self.assertRaises(ValueError):
            pool.release(obj)
        borrowed_again = pool.acquire(second)
        self.assertIs(borrowed_again, obj)
        self.assertEqual(snapshot(borrowed_again), second)
        self.assertEqual(historical, first)


class RunnerLeaseTests(unittest.TestCase):
    def test_lease_from_another_session_cannot_release_current_borrow(self):
        spec = CosmicSpec("Same star", "star", "#123abc", 1)
        issued = []

        def borrow(context):
            issued.append(context.acquire(spec))

        def use_foreign_lease(context):
            current = context.acquire(spec)
            with self.assertRaises(RunnerUsageError):
                context.snapshot(issued[0])
            with self.assertRaises(RunnerUsageError):
                context.release(issued[0])
            self.assertEqual(context.snapshot(current), spec)
            context.release(current)

        for scenario in (borrow, use_foreign_lease):
            # Give each run separate streams while keeping the previous lease
            # object alive in this process. Send replies only after publication.
            read_fd, write_fd = os.pipe()
            with os.fdopen(read_fd, "r") as stdin, os.fdopen(write_fd, "wb") as replies:
                actions = []

                class HostOutput(BytesIO):
                    def write(self, line):
                        action = json.loads(line)["type"]
                        actions.append(action)
                        ack = {"type": "ack", "action": action, "revision": len(actions)}
                        replies.write(json.dumps(ack).encode() + b"\n")
                        replies.flush()
                        return super().write(line)

                replies.write(json.dumps(INIT).encode() + b"\n")
                replies.flush()
                with TextIOWrapper(HostOutput()) as stdout, patch.multiple(
                    sys, stdin=stdin, stdout=stdout
                ):
                    result = run(create_pool(), scenario, snapshot=snapshot)
                self.assertEqual(result, 0)
                self.assertEqual(actions, ["acquire"] if scenario is borrow else ["acquire", "release"])


class RunnerProcessTests(unittest.TestCase):
    def start(self, *args, read_stdout=True):
        env = os.environ.copy()
        env["GALAXY_TEST_PRESENTATION_DELAY"] = "0"
        env["PYTHONIOENCODING"] = "ascii"
        child = subprocess.Popen(
            [sys.executable, "-m", *args],
            cwd=ROOT,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.addCleanup(self.close_child, child)
        self.child = child
        self.stdout = Queue()
        if read_stdout:
            Thread(target=self.read_output, args=(child.stdout, self.stdout), daemon=True).start()
        else:
            child.stdout.close()

    @staticmethod
    def read_output(stream, queue):
        with stream:
            for line in stream:
                queue.put(line)
        queue.put(b"")

    @staticmethod
    def close_child(child):
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        child.stdin.close()
        child.stdout.close()
        child.stderr.close()

    def start_case(self, case, **kwargs):
        self.start("tests.fixtures.python_runner_cases", case, **kwargs)

    def send(self, message, newline=b"\n"):
        self.send_raw(json.dumps(message).encode("utf-8") + newline)

    def send_raw(self, payload):
        self.child.stdin.write(payload)
        self.child.stdin.flush()

    def receive(self):
        try:
            return self.stdout.get(timeout=5)
        except Empty:
            self.fail("Timed out waiting for child stdout")

    def event(self, action):
        raw = self.receive()
        self.assertTrue(raw.endswith(b"\n"), raw)
        self.assertFalse(raw.endswith(b"\r\n"), raw)
        self.assertLessEqual(len(raw) - 1, 8000)
        event = json.loads(raw.decode("utf-8"))
        self.assertEqual(event["type"], action)
        fields = {"type"}
        if action != "reset":
            fields.update(("poolSlotId", "generation"))
            self.assertIsInstance(event["poolSlotId"], str)
            self.assertTrue(re.fullmatch(r"[A-Za-z0-9_-]{1,48}", event["poolSlotId"]))
            self.assertIs(type(event["generation"]), int)
            self.assertGreater(event["generation"], 0)
        if action == "acquire":
            fields.add("data")
            self.assertEqual(set(event["data"]), {"name", "type", "color", "size"})
        self.assertEqual(set(event), fields)
        return event, raw

    def ack(self, action, revision=1):
        self.send({"type": "ack", "action": action, "revision": revision})

    def finish(self, code, *, check_stdout=True):
        self.assertEqual(self.child.wait(timeout=5), code)
        if check_stdout:
            self.assertEqual(self.receive(), b"", "Unexpected event before exit")
        stderr = self.child.stderr.read().decode("utf-8", errors="replace")
        if code:
            self.assertTrue(stderr.strip(), "Expected a diagnostic on stderr")
        return stderr

    def assert_waiting(self):
        with self.assertRaises(Empty):
            self.stdout.get(timeout=0.1)
        self.assertIsNone(self.child.poll())

    def test_demo_orbit_and_explicit_restart(self):
        for reset in (False, True):
            with self.subTest(reset=reset):
                args = ("--reset-on-start",) if reset else ()
                self.start("framework.adapters.python", "--module", DEMO, *args)
                self.assert_waiting()
                self.send(INIT, newline=b"\r\n")
                if reset:
                    self.event("reset")
                    self.assert_waiting()
                    self.ack("reset", 41)
                active = set()
                first = None
                for index, action in enumerate(["acquire"] * 10 + ["release", "acquire"]):
                    event, raw = self.event(action)
                    slot = event["poolSlotId"]
                    if index == 0:
                        first = slot
                        self.assertIn("새벽".encode(), raw)
                    if index == 10:
                        self.assertEqual(len(active), 10)
                        self.assertEqual(slot, first)
                        self.assertEqual(event["generation"], 1)
                        active.remove(slot)
                        self.assertEqual(len(active), 9)
                    else:
                        self.assertNotIn(slot, active)
                        active.add(slot)
                        self.assertEqual(event["generation"], 2 if index == 11 else 1)
                        if index == 11:
                            self.assertEqual(slot, first)
                            self.assertEqual(event["data"], {
                                "name": "Reborn Nova", "type": "star",
                                "color": "#f4bd64", "size": 1.6,
                            })
                    if index == 11:
                        self.assert_waiting()
                    self.ack(action, 43 + index * 2)
                self.assertEqual(len(active), 10)
                self.finish(0)

    def test_run_waits_for_final_ack_and_redirects_prints(self):
        self.start_case("success")
        self.send(INIT)
        event, raw = self.event("acquire")
        self.assertEqual(event["data"]["name"], "새벽 🚀")
        self.assertIn("새벽 🚀".encode(), raw)
        self.assert_waiting()
        self.ack("acquire", 7)
        stderr = self.finish(0)
        self.assertIn("pool acquire", stderr)
        self.assertIn("scenario entered", stderr)
        self.assertIn("final acquire confirmed", stderr)

    def test_reuse_stale_duplicate_and_fabricated_leases(self):
        self.start_case("leases")
        self.send(INIT)
        events = []
        for revision, action in enumerate(
            ("acquire", "release", "acquire", "release", "acquire", "acquire"), 1
        ):
            event, _ = self.event(action)
            events.append(event)
            self.ack(action, revision)
        self.assertIn("fixture assertions passed", self.finish(0))
        slot = events[0]["poolSlotId"]
        self.assertEqual([event["poolSlotId"] for event in events[:5]], [slot] * 5)
        self.assertNotEqual(events[5]["poolSlotId"], slot)
        self.assertEqual([event["generation"] for event in events], [1, 1, 2, 2, 3, 1])

    def test_pool_errors_poison_run_even_when_scenario_catches_them(self):
        for case in (
            "acquire_error", "null_storage", "invalid_projection",
            "mismatched_projection", "cleanup_error", "active_alias", "release_error",
        ):
            with self.subTest(case=case):
                self.start_case(case)
                self.send(INIT)
                if case in ("active_alias", "release_error"):
                    self.event("acquire")
                    self.ack("acquire")
                stderr = self.finish(1)
                self.assertIn("fixture observed fatal error", stderr)
                if case == "cleanup_error":
                    self.assertIn("snapshot", stderr)

    def test_invalid_init_never_enters_scenario(self):
        for invalid in (
            b'{"type":\n',
            b'{"type":"init","participantId":"\xff"}\n',
            b'{"type":"init","participantId":"has space"}\n',
            b'{"type":"init","participantId":0}\n',
            b'{"type":"init","participantId":"runner-tests","other":NaN}\n',
            b'{"type":"ack","action":"acquire","revision":1}\n',
        ):
            with self.subTest(invalid=invalid):
                self.start_case("success")
                self.send_raw(invalid)
                self.assertNotIn("scenario entered", self.finish(1))

    def test_init_eof_or_timeout(self):
        for eof in (False, True):
            with self.subTest(eof=eof):
                self.start_case("success")
                if eof:
                    self.child.stdin.close()
                self.assertNotIn("scenario entered", self.finish(1))

    def test_invalid_or_missing_ack_stops_publication(self):
        for failure, reply in (
            ("wrong action", b'{"type":"ack","action":"release","revision":1}\n'),
            ("invalid revision", b'{"type":"ack","action":"acquire","revision":true}\n'),
            ("unsafe revision", b'{"type":"ack","action":"acquire","revision":9007199254740992}\n'),
            ("rejected", b'{"type":"error","message":"relay rejected fixture"}\n'),
            ("second init", b'{"type":"init","participantId":"runner-tests"}\n'),
            ("malformed", b'{"type":\n'),
            ("oversized", b'{"type":"ack","action":"acquire","revision":1,"padding":"'
             + b'x' * 8000 + b'"}\n'),
            ("eof", None),
            ("timeout", None),
        ):
            with self.subTest(failure=failure):
                self.start_case("transport_error")
                self.send(INIT)
                self.event("acquire")
                if reply is not None:
                    self.send_raw(reply)
                elif failure == "eof":
                    self.child.stdin.close()
                stderr = self.finish(1)
                self.assertIn("fixture observed fatal error", stderr)
                if failure == "rejected":
                    self.assertIn("relay rejected fixture", stderr)

    def test_unsolicited_ack_while_idle(self):
        self.start_case("idle_reply")
        self.send(INIT)
        self.event("acquire")
        self.send_raw(
            b'{"type":"ack","action":"acquire","revision":1}\n'
            b'{"type":"ack","action":"acquire","revision":2}\n'
        )
        self.finish(1)

    def test_reset_rejection_prevents_borrows(self):
        self.start("framework.adapters.python", "--module", DEMO, "--reset-on-start")
        self.send(INIT)
        self.event("reset")
        self.send({"type": "error", "message": "reset denied"})
        self.assertIn("reset denied", self.finish(1))

    def test_release_rejection_stops_publication(self):
        self.start_case("release_transport_error")
        self.send(INIT)
        acquired, _ = self.event("acquire")
        self.ack("acquire")
        released, _ = self.event("release")
        self.assertEqual(released["poolSlotId"], acquired["poolSlotId"])
        self.assertEqual(released["generation"], acquired["generation"])
        self.send({"type": "error", "message": "release denied"})
        stderr = self.finish(1)
        self.assertIn("fixture observed fatal error", stderr)
        self.assertIn("release denied", stderr)

    def test_broken_stdout_pipe_fails_the_run(self):
        self.start_case("transport_error", read_stdout=False)
        self.send(INIT)
        self.assertIn("fixture observed fatal error", self.finish(1, check_stdout=False))

    def test_scenario_exception_does_not_release_active_borrows(self):
        self.start_case("scenario_error")
        self.send(INIT)
        self.event("acquire")
        self.ack("acquire")
        self.assertIn("fixture scenario failure", self.finish(1))

    def test_handled_keyboard_interrupt_exit(self):
        self.start_case("keyboard_interrupt")
        self.send(INIT)
        self.finish(130)
