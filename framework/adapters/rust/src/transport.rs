use std::io::{self, BufRead, Write};
use std::sync::{Arc, Condvar, Mutex};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::Value;

use crate::{RunnerError, Transport, MAX_SAFE_INTEGER};

const MAX_LINE: usize = 8_000;
const INIT_TIMEOUT: Duration = Duration::from_secs(5);
const ACK_TIMEOUT: Duration = Duration::from_secs(2);
const SEND_INTERVAL: Duration = Duration::from_millis(25);

#[derive(Default)]
struct Input {
    awaiting_since: Option<Instant>,
    frame: Option<(Vec<u8>, Instant)>,
    fault: Option<&'static str>,
    eof: bool,
}

type Mailbox = (Mutex<Input>, Condvar);

pub(crate) struct Jsonl {
    mailbox: Arc<Mailbox>,
    started: Instant,
    next_send: Instant,
}

impl Jsonl {
    pub(crate) fn new() -> Result<Self, RunnerError> {
        let started = Instant::now();
        let mailbox = Arc::new((
            Mutex::new(Input {
                awaiting_since: Some(started),
                ..Input::default()
            }),
            Condvar::new(),
        ));
        let inbox = Arc::clone(&mailbox);
        // A reader blocked on open stdin must not hold the process open on exit.
        thread::Builder::new()
            .name("galaxy-stdin".into())
            .spawn(move || read_input(&inbox, io::stdin().lock()))
            .map_err(|error| fail("init", error))?;
        Ok(Self {
            mailbox,
            started,
            next_send: started,
        })
    }

    pub(crate) fn init(&self) -> Result<String, RunnerError> {
        let msg = self.read("init", self.started + INIT_TIMEOUT)?;
        if let Some(id) = msg["participantId"].as_str() {
            if msg["type"] == "init"
                && (1..=32).contains(&id.len())
                && id
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
            {
                return Ok(id.to_owned());
            }
        }
        Err(fail("init", "expected init with a valid participantId"))
    }

    fn read(&self, phase: &str, deadline: Instant) -> Result<Value, RunnerError> {
        let (lock, ready) = &*self.mailbox;
        let mut input = lock.lock().unwrap();
        let line = loop {
            if let Some(fault) = input.fault {
                return Err(fail(phase, fault));
            }
            if let Some((line, received)) = input.frame.take() {
                input.awaiting_since = None;
                if received > deadline {
                    return Err(fail(phase, "timed out"));
                }
                break line;
            }
            if input.eof {
                return Err(fail(phase, "stdin reached EOF"));
            }
            let remaining = deadline.saturating_duration_since(Instant::now());
            if remaining.is_zero() {
                return Err(fail(phase, "timed out"));
            }
            input = ready.wait_timeout(input, remaining).unwrap().0;
        };
        drop(input);
        let utf8 = std::str::from_utf8(&line).map_err(|error| fail(phase, error))?;
        let msg: Value = serde_json::from_str(utf8).map_err(|error| fail(phase, error))?;
        if !msg.is_object() {
            return Err(fail(phase, "expected a JSON object"));
        }
        Ok(msg)
    }
}

impl Transport for Jsonl {
    fn check_idle(&self, sending: bool) -> Result<(), RunnerError> {
        check_input(&self.mailbox.0.lock().unwrap(), sending, "idle")
    }

    fn exchange(&mut self, action: &str, event: Value) -> Result<(), RunnerError> {
        let phase = match event["poolSlotId"].as_str() {
            Some(slot) => format!("{action} slot {slot} generation {}", event["generation"]),
            None => action.to_owned(),
        };
        let mut payload = serde_json::to_vec(&event).map_err(|error| fail(&phase, error))?;
        if payload.len() > MAX_LINE {
            return Err(fail(&phase, "event exceeds 8000 bytes"));
        }
        payload.push(b'\n');
        while let Some(remaining) = self.next_send.checked_duration_since(Instant::now()) {
            thread::sleep(remaining);
        }
        let sent = {
            let mut input = self.mailbox.0.lock().unwrap();
            check_input(&input, true, &phase)?;
            input.awaiting_since = Some(Instant::now());
            let mut stdout = io::stdout().lock();
            stdout
                .write_all(&payload)
                .and_then(|()| stdout.flush())
                .map_err(|error| fail(&phase, format_args!("stdout write failed: {error}")))?;
            Instant::now()
        };
        self.next_send = sent + SEND_INTERVAL;
        let reply = self.read(&format!("{phase} ack"), sent + ACK_TIMEOUT)?;
        if reply["type"] == "error" {
            if let Some(message) = reply["message"].as_str() {
                return Err(fail(&phase, format_args!("remote rejection: {message:?}")));
            }
        }
        let valid_revision = reply["revision"].as_f64().is_some_and(|revision| {
            (1.0..=MAX_SAFE_INTEGER as f64).contains(&revision) && revision.fract() == 0.0
        });
        if reply["type"] != "ack" || reply["action"] != action || !valid_revision {
            return Err(fail(&phase, "expected matching ack with a valid revision"));
        }
        Ok(())
    }
}

fn check_input(input: &Input, sending: bool, phase: &str) -> Result<(), RunnerError> {
    if let Some(fault) = input.fault {
        return Err(fail(phase, fault));
    }
    if sending && input.eof {
        return Err(fail(phase, "stdin reached EOF before next event"));
    }
    Ok(())
}

fn fail(phase: &str, detail: impl std::fmt::Display) -> RunnerError {
    RunnerError::Transport(format!("{phase}: {detail}"))
}

fn read_input(mailbox: &Mailbox, mut reader: impl BufRead) {
    let (lock, ready) = mailbox;
    let mut partial = Vec::new();
    loop {
        let chunk = reader.fill_buf();
        let received = Instant::now();
        let mut input = lock.lock().unwrap();
        match chunk {
            Err(err) if err.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => input.fault = Some("stdin read failed"),
            Ok([]) => {
                input.eof = true;
                if !partial.is_empty() {
                    input.fault = Some("unterminated JSONL input at EOF");
                }
            }
            Ok(bytes) => {
                for piece in bytes.split_inclusive(|&b| b == b'\n') {
                    let (payload, ended) = match piece.strip_suffix(b"\n") {
                        Some(payload) => (payload, true),
                        None => (piece, false),
                    };
                    if input.frame.is_some() || !input.awaiting_since.is_some_and(|t| t <= received)
                    {
                        input.fault = Some("unsolicited control message");
                        break;
                    }
                    let optional_cr =
                        usize::from(payload.last().or(partial.last()) == Some(&b'\r'));
                    if partial.len() + payload.len() > MAX_LINE + optional_cr {
                        input.fault = Some("JSONL input exceeds 8000 bytes");
                        break;
                    }
                    partial.extend_from_slice(payload);
                    if ended {
                        if partial.last() == Some(&b'\r') {
                            partial.pop();
                        }
                        input.frame = Some((std::mem::take(&mut partial), received));
                    }
                }
                let count = bytes.len();
                reader.consume(count);
            }
        }
        ready.notify_one();
        if input.eof || input.fault.is_some() {
            return;
        }
    }
}
