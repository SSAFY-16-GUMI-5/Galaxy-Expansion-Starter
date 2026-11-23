#![forbid(unsafe_code)]

use std::process::ExitCode;
use std::thread;
use std::time::Duration;

use galaxy_runner::{RunnerError, ScenarioContext};
use galaxy_rust_fixture::{aurora, nova, FixturePool};

fn scenario(context: &mut ScenarioContext<'_, FixturePool>) -> Result<(), RunnerError> {
    let delay = match std::env::var("GALAXY_TEST_PRESENTATION_DELAY") {
        Ok(value) => value
            .parse::<f64>()
            .ok()
            .filter(|seconds| (0.0..=3.0).contains(seconds))
            .map(Duration::from_secs_f64)
            .ok_or_else(|| {
                RunnerError::Scenario("presentation delay must be 0 to 3 seconds".into())
            })?,
        Err(std::env::VarError::NotPresent) => Duration::ZERO,
        Err(_) => {
            return Err(RunnerError::Scenario(
                "presentation delay must be UTF-8".into(),
            ))
        }
    };
    let first = context.acquire(aurora())?;
    thread::sleep(delay);
    context.release(&first)?;
    thread::sleep(delay);
    let reborn = context.acquire(nova())?;
    assert_eq!(context.snapshot(&reborn)?, nova());
    Ok(())
}

fn main() -> ExitCode {
    galaxy_runner::cli(FixturePool::default(), scenario)
}
