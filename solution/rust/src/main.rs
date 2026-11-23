#![forbid(unsafe_code)]

use std::process::ExitCode;

use galaxy_runner::{Borrow, CosmicSpec, Pool, RunnerError, ScenarioContext};

// TODO: Define CosmicObject. Keep objects and their StorageTokens in the pool.
// Pick a capacity policy and a way to track available and borrowed storage.
struct ObjectPool;

// TODO: Add private fields to locate storage and identify this specific borrow.
struct Handle;

impl Pool for ObjectPool {
    type Handle = Handle;

    fn acquire(&mut self, _spec: &CosmicSpec) -> Result<Borrow<Handle>, String> {
        // TODO: Choose free storage or allocate it, initialize all fields, then
        // return its stable token and a fresh handle. Handle capacity explicitly.
        Err("implement ObjectPool::acquire".into())
    }

    fn snapshot(&self, _handle: &Handle) -> Result<CosmicSpec, String> {
        // TODO: Check the handle and copy the actual object's current fields.
        Err("implement ObjectPool::snapshot".into())
    }

    fn release(&mut self, _handle: Handle) -> Result<(), String> {
        // TODO: Check the handle and mark its storage available for reuse.
        Err("implement ObjectPool::release".into())
    }
}

fn scenario(_context: &mut ScenarioContext<'_, ObjectPool>) -> Result<(), RunnerError> {
    // TODO: Acquire, inspect and release an object, then acquire the same
    // storage with different fields. Keep the sequence finite.
    Err(RunnerError::Scenario(
        "implement the participant scenario".into(),
    ))
}

fn main() -> ExitCode {
    galaxy_runner::cli(ObjectPool, scenario)
}
