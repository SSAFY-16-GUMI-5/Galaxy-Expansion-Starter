"""Bounded, synchronous Protocol v1 exchanges over process pipes."""

import json
import os
import re
from threading import Condition, Thread
from time import monotonic, sleep
from typing import BinaryIO

MAX_LINE_BYTES = 8_000
MAX_SAFE_INTEGER = 9_007_199_254_740_991
SEND_INTERVAL = 0.025
PARTICIPANT_ID = re.compile(r"[A-Za-z0-9_-]{1,32}")


class RunnerTransportError(RuntimeError):
    """The control stream failed or an event was not confirmed."""


def _reject_constant(value: str) -> None:
    raise ValueError(f"Invalid JSON constant {value}")


class JsonlTransport:
    def __init__(self, input_fd: int, output: BinaryIO):
        self._output = output
        self._condition = Condition()
        self._awaiting_since: float | None = monotonic()  # The first line must be init.
        self._reply: tuple[bytes, float] | None = None
        self._fault: str | None = None
        self._eof = False
        self._closed = False
        self._next_send = 0.0
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.setmode(input_fd, os.O_BINARY)
            # Raw OS reads cannot hold Python's buffered stdin lock at shutdown.
            Thread(target=self._read_lines, args=(input_fd,), daemon=True).start()
        except (OSError, RuntimeError) as exc:
            raise RunnerTransportError(f"init: cannot start input reader: {exc}") from exc

    def _read_lines(self, fd: int) -> None:
        partial = b""
        while True:
            try:
                chunk = os.read(fd, 4096)
                received = monotonic()
            except OSError as exc:
                with self._condition:
                    self._fault = f"stdin read failed: {exc}"
                    self._condition.notify_all()
                return

            with self._condition:
                if self._closed:
                    return
                if not chunk:
                    self._eof = True
                    if partial:
                        self._fault = "unterminated JSONL input at EOF"
                else:
                    *lines, partial = (partial + chunk).split(b"\n")
                    for line in lines:
                        self._receive_line(line.removesuffix(b"\r"), received)
                        if self._fault:
                            break
                    if partial and not self._fault:
                        if not self._expects_input(received):
                            self._fault = "unsolicited control message"
                        elif len(partial.removesuffix(b"\r")) > MAX_LINE_BYTES:
                            # Allow one extra byte for a pending CRLF terminator.
                            self._fault = "JSONL input exceeds 8000 bytes"
                self._condition.notify_all()
                if self._fault or self._eof:
                    return

    def _expects_input(self, received: float) -> bool:
        return (
            self._awaiting_since is not None
            and self._awaiting_since <= received
            and self._reply is None
        )

    def _receive_line(self, line: bytes, received: float) -> None:
        if len(line) > MAX_LINE_BYTES:
            self._fault = "JSONL input exceeds 8000 bytes"
        elif not self._expects_input(received):
            self._fault = "unsolicited control message"
        else:
            self._reply = (line, received)

    def _check_fault(self, phase: str) -> None:
        if self._fault:
            raise RunnerTransportError(f"{phase}: {self._fault}")

    def check_idle(self, *, sending: bool = False) -> None:
        with self._condition:
            self._check_fault("idle")
            if sending and self._eof:
                raise RunnerTransportError("idle: stdin reached EOF before next event")

    def _read_object(self, phase: str, deadline: float) -> dict:
        with self._condition:
            while True:
                self._check_fault(phase)
                if self._reply is not None:
                    line, received = self._reply
                    self._reply = None
                    self._awaiting_since = None
                    if received > deadline:
                        raise RunnerTransportError(f"{phase}: timed out")
                    break
                if self._eof:
                    raise RunnerTransportError(f"{phase}: stdin reached EOF")
                remaining = deadline - monotonic()
                if remaining <= 0:
                    raise RunnerTransportError(f"{phase}: timed out")
                self._condition.wait(remaining)

        try:
            value = json.loads(line.decode("utf-8"), parse_constant=_reject_constant)
        except (ValueError, RecursionError) as exc:
            raise RunnerTransportError(f"{phase}: invalid UTF-8 JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise RunnerTransportError(f"{phase}: expected a JSON object")
        return value

    def read_init(self, deadline: float) -> str:
        message = self._read_object("init", deadline)
        participant_id = message.get("participantId")
        if (
            message.get("type") != "init"
            or not isinstance(participant_id, str)
            or not PARTICIPANT_ID.fullmatch(participant_id)
        ):
            raise RunnerTransportError("init: expected init with a valid participantId")
        return participant_id

    def exchange(self, event: dict, timeout: float) -> None:
        action = event["type"]
        phase = action
        if "poolSlotId" in event:
            phase = f"{action} slot {event['poolSlotId']} generation {event['generation']}"
        try:
            payload = json.dumps(
                event, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RunnerTransportError(f"{phase}: cannot encode event: {exc}") from exc
        if len(payload) > MAX_LINE_BYTES:
            raise RunnerTransportError(f"{phase}: event exceeds 8000 bytes")

        remaining = self._next_send - monotonic()
        if remaining > 0:
            sleep(remaining)
        line = payload + b"\n"
        with self._condition:
            self._check_fault(phase)
            if self._eof:
                raise RunnerTransportError(f"{phase}: stdin reached EOF before writing event")
            self._awaiting_since = monotonic()
            try:
                if self._output.write(line) != len(line):
                    raise OSError("short stdout write")
                self._output.flush()
            except (OSError, ValueError) as exc:
                # A buffered pipe can try to flush the failed write at interpreter exit.
                try:
                    self._output.close()
                except (OSError, ValueError):
                    pass
                raise RunnerTransportError(f"{phase}: stdout write failed: {exc}") from exc
            sent_at = monotonic()
            self._next_send = sent_at + SEND_INTERVAL

        reply = self._read_object(f"{phase} ack", sent_at + timeout)
        if reply.get("type") == "error" and isinstance(reply.get("message"), str):
            raise RunnerTransportError(f"{phase}: remote rejection: {reply['message']!r}")
        revision = reply.get("revision")
        if (
            reply.get("type") != "ack"
            or reply.get("action") != action
            or type(revision) not in (int, float)
            or not 1 <= revision <= MAX_SAFE_INTEGER
            or revision != int(revision)
        ):
            raise RunnerTransportError(f"{phase}: expected matching ack with a valid revision")

    def close(self) -> None:
        with self._condition:
            self._closed = True
