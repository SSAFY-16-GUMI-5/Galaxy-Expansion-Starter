#![forbid(unsafe_code)]

#[cfg(test)]
mod tests;
mod transport;

use std::ffi::OsStr;
use std::fmt;
use std::panic::{catch_unwind, AssertUnwindSafe};
use std::process::ExitCode;
use std::rc::Rc;

use serde_json::{json, Value};
use transport::Jsonl;

const MAX_SLOTS: usize = 500;
const MAX_SAFE_INTEGER: u64 = 9_007_199_254_740_991;

#[derive(Clone, Debug, PartialEq)]
pub struct CosmicSpec {
    pub name: String,
    pub kind: Kind,
    pub color: String,
    pub size: f64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind {
    Seed,
    Star,
    Planet,
}

impl CosmicSpec {
    fn validate(&self) -> Result<(), &'static str> {
        // ECMAScript trim includes BOM and excludes U+0085.
        let blank = self
            .name
            .trim_matches(|c: char| (c.is_whitespace() && c != '\u{0085}') || c == '\u{feff}');
        if blank.is_empty() || self.name.encode_utf16().count() > 40 {
            return Err("name must be nonblank and at most 40 UTF-16 code units");
        }
        let color = self.color.as_bytes();
        if color.len() != 7 || color[0] != b'#' || !color[1..].iter().all(u8::is_ascii_hexdigit) {
            return Err("color must be #RRGGBB");
        }
        if !(0.3..=3.5).contains(&self.size) {
            return Err("size must be a finite number from 0.3 to 3.5");
        }
        Ok(())
    }

    fn wire(&self) -> Value {
        let kind = match self.kind {
            Kind::Seed => "seed",
            Kind::Star => "star",
            Kind::Planet => "planet",
        };
        json!({"name": self.name, "type": kind, "color": self.color, "size": self.size})
    }
}

/// Assign one token when allocating storage. Keep it with that storage
/// for its lifetime and clone it for each borrow of that storage.
#[derive(Clone, Debug)]
pub struct StorageToken(Rc<()>);

impl StorageToken {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn same_storage(&self, other: &Self) -> bool {
        Rc::ptr_eq(&self.0, &other.0)
    }
}

impl Default for StorageToken {
    fn default() -> Self {
        Self(Rc::new(()))
    }
}

/// A participant pool keeps the actual object and supplies its borrow handle.
pub struct Borrow<H> {
    pub storage: StorageToken,
    pub handle: H,
}

pub trait Pool {
    type Handle;

    fn acquire(&mut self, spec: &CosmicSpec) -> Result<Borrow<Self::Handle>, String>;
    fn snapshot(&self, handle: &Self::Handle) -> Result<CosmicSpec, String>;
    fn release(&mut self, handle: Self::Handle) -> Result<(), String>;
}

/// An opaque reference to a single issuance. Every clone expires together.
#[derive(Clone, Debug)]
pub struct Lease(Rc<()>);

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum RunnerError {
    Usage(String),
    Pool(String),
    Transport(String),
    Scenario(String),
}

impl fmt::Display for RunnerError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        let (phase, detail) = match self {
            Self::Usage(detail) => ("usage", detail),
            Self::Pool(detail) => ("pool", detail),
            Self::Transport(detail) => ("transport", detail),
            Self::Scenario(detail) => ("scenario", detail),
        };
        write!(f, "{phase}: {detail}")
    }
}

impl std::error::Error for RunnerError {}

struct Active<H> {
    lease: Lease,
    handle: H,
    snapshot: CosmicSpec,
}

struct Slot<H> {
    storage: StorageToken,
    generation: u64,
    active: Option<Active<H>>,
}

trait Transport {
    fn check_idle(&self, sending: bool) -> Result<(), RunnerError>;
    fn exchange(&mut self, action: &str, event: Value) -> Result<(), RunnerError>;
}

pub struct ScenarioContext<'a, P: Pool> {
    pool: P,
    transport: &'a mut dyn Transport,
    participant_id: String,
    slots: Vec<Slot<P::Handle>>,
    failure: Option<RunnerError>,
}

impl<P: Pool> ScenarioContext<'_, P> {
    pub fn participant_id(&self) -> &str {
        &self.participant_id
    }

    pub fn acquire(&mut self, spec: CosmicSpec) -> Result<Lease, RunnerError> {
        self.check(true)?;
        spec.validate()
            .map_err(|detail| RunnerError::Usage(detail.into()))?;
        let result = self.acquire_validated(&spec);
        self.record_failure(result)
    }

    pub fn snapshot(&mut self, lease: &Lease) -> Result<CosmicSpec, RunnerError> {
        self.check(false)?;
        let (_, active) = self.active(lease)?;
        Ok(active.snapshot.clone())
    }

    pub fn release(&mut self, lease: &Lease) -> Result<(), RunnerError> {
        self.check(true)?;
        let (index, _) = self.active(lease)?;
        let slot = &mut self.slots[index];
        let active = slot.active.take().expect("checked active lease");
        let result = domain("release", || self.pool.release(active.handle)).and_then(|()| {
            self.transport.exchange(
                "release",
                json!({
                    "type": "release",
                    "poolSlotId": (index + 1).to_string(),
                    "generation": slot.generation,
                }),
            )
        });
        self.record_failure(result)
    }

    fn acquire_validated(&mut self, spec: &CosmicSpec) -> Result<Lease, RunnerError> {
        let Borrow { storage, handle } = domain("acquire", || self.pool.acquire(spec))?;
        let index = self
            .slots
            .iter()
            .position(|slot| slot.storage.same_storage(&storage));
        if index.is_some_and(|i| self.slots[i].active.is_some()) {
            return Err(RunnerError::Pool(
                "acquire returned already active storage".into(),
            ));
        }

        let prepared = self.prepare_acquire(index, &handle, spec);
        let (index, generation, snapshot) = match prepared {
            Ok(prepared) => prepared,
            Err(failure) => {
                // This borrow was never published, and it cannot alias active storage.
                let _ = domain("cleanup release", || self.pool.release(handle));
                return Err(failure);
            }
        };
        let lease = Lease(Rc::new(()));
        let slot = Slot {
            storage,
            generation,
            active: Some(Active {
                lease: lease.clone(),
                handle,
                snapshot: snapshot.clone(),
            }),
        };
        if index == self.slots.len() {
            self.slots.push(slot);
        } else {
            self.slots[index] = slot;
        }
        self.transport.exchange(
            "acquire",
            json!({
                "type": "acquire",
                "poolSlotId": (index + 1).to_string(),
                "generation": generation,
                "data": snapshot.wire(),
            }),
        )?;
        Ok(lease)
    }

    fn prepare_acquire(
        &self,
        index: Option<usize>,
        handle: &P::Handle,
        spec: &CosmicSpec,
    ) -> Result<(usize, u64, CosmicSpec), RunnerError> {
        let (index, generation) = match index {
            Some(i) if self.slots[i].generation < MAX_SAFE_INTEGER => {
                (i, self.slots[i].generation + 1)
            }
            None if self.slots.len() < MAX_SLOTS => (self.slots.len(), 1),
            Some(_) => return Err(RunnerError::Pool("generation limit exceeded".into())),
            None => {
                return Err(RunnerError::Pool(
                    "participant slot limit (500) exceeded".into(),
                ))
            }
        };
        let snapshot = domain("snapshot", || self.pool.snapshot(handle))?;
        snapshot
            .validate()
            .map_err(|detail| RunnerError::Pool(format!("snapshot: {detail}")))?;
        if &snapshot != spec {
            return Err(RunnerError::Pool(
                "snapshot does not match the requested fields".into(),
            ));
        }
        Ok((index, generation, snapshot))
    }

    fn active(&self, lease: &Lease) -> Result<(usize, &Active<P::Handle>), RunnerError> {
        self.slots
            .iter()
            .enumerate()
            .find_map(|(index, slot)| {
                let active = slot.active.as_ref()?;
                Rc::ptr_eq(&active.lease.0, &lease.0).then_some((index, active))
            })
            .ok_or_else(|| RunnerError::Usage("lease is foreign or expired".into()))
    }

    fn check(&mut self, sending: bool) -> Result<(), RunnerError> {
        if let Some(failure) = &self.failure {
            return Err(failure.clone());
        }
        let result = self.transport.check_idle(sending);
        self.record_failure(result)
    }

    fn record_failure<T>(&mut self, result: Result<T, RunnerError>) -> Result<T, RunnerError> {
        if let Err(failure) = &result {
            self.failure = Some(failure.clone());
        }
        result
    }
}

fn domain<T>(operation: &str, call: impl FnOnce() -> Result<T, String>) -> Result<T, RunnerError> {
    catch_unwind(AssertUnwindSafe(call))
        .map_err(|_| RunnerError::Pool(format!("{operation}: panicked")))?
        .map_err(|detail| RunnerError::Pool(format!("{operation}: {detail}")))
}

/// Runs one fresh pool and scenario with the process streams. Use once per process.
pub fn run<P: Pool>(
    pool: P,
    scenario: impl FnOnce(&mut ScenarioContext<'_, P>) -> Result<(), RunnerError>,
    reset_on_start: bool,
) -> Result<(), RunnerError> {
    let mut transport = Jsonl::new()?;
    let participant_id = transport.init()?;
    if reset_on_start {
        transport.exchange("reset", json!({"type": "reset"}))?;
    }
    let mut context = ScenarioContext {
        pool,
        transport: &mut transport,
        participant_id,
        slots: Vec::new(),
        failure: None,
    };
    let result = catch_unwind(AssertUnwindSafe(|| scenario(&mut context)))
        .unwrap_or_else(|_| Err(RunnerError::Scenario("panicked".into())));
    context.check(false)?;
    result
}

/// Process entry point shared by the participant and fixture binaries.
pub fn cli<P: Pool>(
    pool: P,
    scenario: impl FnOnce(&mut ScenarioContext<'_, P>) -> Result<(), RunnerError>,
) -> ExitCode {
    let mut args = std::env::args_os().skip(1);
    let reset = match args.next() {
        None => false,
        Some(flag) if flag == OsStr::new("--reset-on-start") && args.next().is_none() => true,
        _ => {
            eprintln!("Usage: galaxy runner executable [--reset-on-start]");
            return ExitCode::from(2);
        }
    };
    match run(pool, scenario, reset) {
        Ok(()) => ExitCode::SUCCESS,
        Err(failure) => {
            eprintln!("[galaxy-runner] {failure}");
            ExitCode::FAILURE
        }
    }
}
