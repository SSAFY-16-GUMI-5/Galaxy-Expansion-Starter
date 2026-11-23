use std::io::{BufRead, BufReader, Read, Write};
use std::process::{Child, Command, Stdio};
use std::sync::mpsc::{self, Receiver, RecvTimeoutError};
use std::thread;
use std::time::{Duration, Instant};

use serde_json::{json, Value};

struct Producer {
    child: Child,
    stdout: Receiver<Vec<u8>>,
}

impl Producer {
    fn start(reset: bool) -> Self {
        let mut command = Command::new(env!("CARGO_BIN_EXE_galaxy-rust-fixture"));
        if reset {
            command.arg("--reset-on-start");
        }
        let mut child = command
            .env_remove("GALAXY_TEST_PRESENTATION_DELAY")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        let mut output = BufReader::new(child.stdout.take().unwrap());
        let (sender, stdout) = mpsc::channel();
        thread::spawn(move || {
            let mut line = Vec::new();
            while output.read_until(b'\n', &mut line).unwrap() != 0 {
                if sender.send(std::mem::take(&mut line)).is_err() {
                    break;
                }
            }
        });
        Self { child, stdout }
    }

    fn send(&mut self, bytes: &[u8]) {
        let input = self.child.stdin.as_mut().unwrap();
        input.write_all(bytes).unwrap();
        input.flush().unwrap();
    }

    fn init(&mut self) {
        self.send(b"{\"type\":\"init\",\"participantId\":\"rust-native\"}\r\n");
    }

    fn ack(&mut self, action: &str, revision: u64) {
        let line = format!(
            "{}\n",
            json!({"type": "ack", "action": action, "revision": revision})
        );
        self.send(line.as_bytes());
    }

    fn event(&self) -> Value {
        let line = self.stdout.recv_timeout(Duration::from_secs(4)).unwrap();
        assert_eq!(line.last(), Some(&b'\n'));
        assert!(!line.ends_with(b"\r\n"));
        serde_json::from_slice(&line).unwrap()
    }

    fn finish(mut self, expected_code: i32) -> String {
        let deadline = Instant::now() + Duration::from_secs(6);
        let status = loop {
            if let Some(status) = self.child.try_wait().unwrap() {
                break status;
            }
            assert!(Instant::now() < deadline, "producer failed to exit");
            thread::sleep(Duration::from_millis(5));
        };
        let mut diagnostics = String::new();
        self.child
            .stderr
            .take()
            .unwrap()
            .read_to_string(&mut diagnostics)
            .unwrap();
        assert_eq!(status.code(), Some(expected_code), "{diagnostics}");
        assert_eq!(
            self.stdout.recv_timeout(Duration::from_secs(1)),
            Err(RecvTimeoutError::Disconnected)
        );
        diagnostics
    }
}

impl Drop for Producer {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

#[test]
fn confirms_reset_and_each_event_through_final_ack_with_stdin_open() {
    let mut producer = Producer::start(true);
    producer.init();
    assert_eq!(producer.event(), json!({"type":"reset"}));
    assert_eq!(
        producer.stdout.recv_timeout(Duration::from_millis(65)),
        Err(RecvTimeoutError::Timeout)
    );
    producer.ack("reset", 5);
    let first = producer.event();
    assert_eq!(
        first,
        json!({
            "type":"acquire", "poolSlotId":"1", "generation":1,
            "data":{"name":"오로라 ✨", "type":"star", "color":"#5dcaff", "size":1.2}
        })
    );
    producer.ack("acquire", 11);
    assert_eq!(
        producer.event(),
        json!({"type":"release", "poolSlotId":"1", "generation":1})
    );
    producer.ack("release", 13);
    assert_eq!(
        producer.event(),
        json!({
            "type":"acquire", "poolSlotId":"1", "generation":2,
            "data":{"name":"다시 태어난 별", "type":"planet", "color":"#a78bfa", "size":1.6}
        })
    );
    assert_eq!(
        producer.stdout.recv_timeout(Duration::from_millis(65)),
        Err(RecvTimeoutError::Timeout)
    );
    assert!(producer.child.try_wait().unwrap().is_none());
    producer.ack("acquire", 57);
    assert!(producer.finish(0).is_empty());
}

#[test]
fn rejects_invalid_init_streams_before_sending_any_event() {
    for input in [
        b"\xff\n".to_vec(),
        b"broken\n".to_vec(),
        b"[]\n".to_vec(),
        b"{\"type\":\"init\",\"participantId\":\"bad id\"}\n".to_vec(),
        b"{\"type\":\"init\",\"participantId\":\"ok\"}\n{\"type\":\"ack\"}\n".to_vec(),
        vec![b'x'; 8001],
    ] {
        let mut producer = Producer::start(false);
        producer.send(&input);
        assert!(producer.finish(1).contains("init"));
    }
}

#[test]
fn invalid_replies_stop_after_first_event() {
    for (reply, diagnostic) in [
        (
            "{\"type\":\"ack\",\"action\":\"release\",\"revision\":1}\n",
            "matching ack",
        ),
        (
            "{\"type\":\"ack\",\"action\":\"acquire\",\"revision\":9007199254740992}\n",
            "valid revision",
        ),
        (
            "{\"type\":\"error\",\"message\":\"try again\"}\n",
            "remote rejection",
        ),
        (
            "{\"type\":\"init\",\"participantId\":\"repeat\"}\n",
            "matching ack",
        ),
    ] {
        let mut producer = Producer::start(false);
        producer.init();
        assert_eq!(producer.event()["type"], "acquire");
        producer.send(reply.as_bytes());
        assert!(producer.finish(1).contains(diagnostic));
    }
}

#[test]
fn missing_ack_times_out_and_early_eof_aborts() {
    let mut stalled = Producer::start(false);
    stalled.init();
    assert_eq!(stalled.event()["type"], "acquire");
    assert!(stalled.finish(1).contains("timed out"));

    let mut closed = Producer::start(false);
    closed.init();
    assert_eq!(closed.event()["type"], "acquire");
    drop(closed.child.stdin.take());
    assert!(closed.finish(1).contains("EOF"));
}

#[test]
fn accepts_split_crlf_at_the_byte_limit_and_decimal_safe_integer_revision() {
    let mut producer = Producer::start(false);
    let mut init = br#"{"type":"init","participantId":"exact"}"#.to_vec();
    init.resize(8000, b' ');
    producer.send(&init);
    producer.send(b"\r");
    producer.send(b"\n");
    assert_eq!(producer.event()["type"], "acquire");
    producer.ack("acquire", 1);
    assert_eq!(producer.event()["type"], "release");
    producer.ack("release", 2);
    assert_eq!(producer.event()["generation"], 2);
    producer.send(b"{\"type\":\"ack\",\"action\":\"acquire\",\"revision\":9007199254740991.0}\n");
    producer.finish(0);
}
