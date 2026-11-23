use super::*;

#[derive(Default)]
struct Recorded(Vec<Value>);

impl Transport for Recorded {
    fn check_idle(&self, _: bool) -> Result<(), RunnerError> {
        Ok(())
    }

    fn exchange(&mut self, _: &str, event: Value) -> Result<(), RunnerError> {
        self.0.push(event);
        Ok(())
    }
}

#[derive(Default)]
struct TestPool {
    storage: StorageToken,
    distinct: bool,
    calls: Vec<&'static str>,
    bad_projection: bool,
    fail_acquire: bool,
}

impl Pool for TestPool {
    type Handle = CosmicSpec;

    fn acquire(&mut self, spec: &CosmicSpec) -> Result<Borrow<Self::Handle>, String> {
        self.calls.push("acquire");
        if self.fail_acquire {
            return Err("capacity exhausted".into());
        }
        let storage = if self.distinct {
            StorageToken::new()
        } else {
            self.storage.clone()
        };
        Ok(Borrow {
            storage,
            handle: spec.clone(),
        })
    }

    fn snapshot(&self, handle: &Self::Handle) -> Result<CosmicSpec, String> {
        let mut snapshot = handle.clone();
        if self.bad_projection {
            snapshot.size = 2.0;
        }
        Ok(snapshot)
    }

    fn release(&mut self, _: Self::Handle) -> Result<(), String> {
        self.calls.push("release");
        Ok(())
    }
}

fn session(transport: &mut Recorded) -> ScenarioContext<'_, TestPool> {
    ScenarioContext {
        pool: TestPool::default(),
        transport,
        participant_id: "tester".into(),
        slots: Vec::new(),
        failure: None,
    }
}

fn spec(name: &str) -> CosmicSpec {
    CosmicSpec {
        name: name.into(),
        kind: Kind::Seed,
        color: "#abcdef".into(),
        size: 1.0,
    }
}

#[test]
fn tracks_generations_and_invalidates_every_old_lease() {
    let mut recorded = Recorded::default();
    {
        let mut context = session(&mut recorded);
        let first = context.acquire(spec("first")).unwrap();
        let history = context.snapshot(&first).unwrap();
        let mut other = Recorded::default();
        let foreign = session(&mut other).acquire(spec("foreign")).unwrap();
        assert!(matches!(
            context.release(&foreign),
            Err(RunnerError::Usage(_))
        ));
        context.release(&first).unwrap();
        assert!(matches!(
            context.release(&first),
            Err(RunnerError::Usage(_))
        ));
        let second = context.acquire(spec("second")).unwrap();
        assert!(matches!(
            context.snapshot(&first),
            Err(RunnerError::Usage(_))
        ));
        assert!(matches!(
            context.release(&first),
            Err(RunnerError::Usage(_))
        ));
        assert_eq!(context.snapshot(&second).unwrap(), spec("second"));
        assert_eq!(history, spec("first"));
        assert_eq!(context.pool.calls, ["acquire", "release", "acquire"]);
    }
    assert_eq!(
        recorded.0,
        [
            json!({"type": "acquire", "poolSlotId": "1", "generation": 1, "data": spec("first").wire()}),
            json!({"type": "release", "poolSlotId": "1", "generation": 1}),
            json!({"type": "acquire", "poolSlotId": "1", "generation": 2, "data": spec("second").wire()}),
        ]
    );
}

#[test]
fn an_active_alias_poisons_without_releasing_the_active_handle() {
    let mut recorded = Recorded::default();
    let mut context = session(&mut recorded);
    let first = context.acquire(spec("first")).unwrap();
    let failure = context.acquire(spec("alias")).unwrap_err();
    assert!(matches!(failure, RunnerError::Pool(_)));
    assert_eq!(context.release(&first), Err(failure));
    assert_eq!(context.pool.calls, ["acquire", "acquire"]);
    assert_eq!(recorded.0.len(), 1);
}

#[test]
fn invalid_input_is_recoverable_and_bad_projection_cleans_up_the_local_borrow() {
    let mut recorded = Recorded::default();
    let mut context = session(&mut recorded);
    assert!(matches!(
        context.acquire(spec("\u{feff} ")),
        Err(RunnerError::Usage(_))
    ));
    assert!(matches!(
        context.acquire(spec(&"🌟".repeat(21))),
        Err(RunnerError::Usage(_))
    ));
    assert!(context.pool.calls.is_empty());
    context.pool.bad_projection = true;
    let failure = context.acquire(spec("\u{0085}")).unwrap_err();
    assert!(matches!(failure, RunnerError::Pool(_)));
    assert_eq!(context.acquire(spec("too late")).unwrap_err(), failure);
    assert_eq!(context.pool.calls, ["acquire", "release"]);
    assert!(recorded.0.is_empty());
}

#[test]
fn pool_failure_stops_the_session() {
    let mut recorded = Recorded::default();
    let mut context = session(&mut recorded);
    context.pool.fail_acquire = true;
    let failure = context.acquire(spec("first")).unwrap_err();
    assert!(matches!(failure, RunnerError::Pool(_)));
    assert_eq!(context.acquire(spec("too late")).unwrap_err(), failure);
    assert_eq!(context.pool.calls, ["acquire"]);
    assert!(recorded.0.is_empty());
}

#[test]
fn different_equal_objects_get_distinct_slots_and_the_501st_is_rejected() {
    let mut recorded = Recorded::default();
    let mut context = session(&mut recorded);
    context.pool.distinct = true;
    for _ in 0..MAX_SLOTS {
        context.acquire(spec("same")).unwrap();
    }
    assert!(matches!(
        context.acquire(spec("same")),
        Err(RunnerError::Pool(_))
    ));
    assert_eq!(context.pool.calls.last(), Some(&"release"));
    assert_eq!(recorded.0.len(), MAX_SLOTS);
    for (index, event) in recorded.0.iter().enumerate() {
        assert_eq!(event["poolSlotId"], (index + 1).to_string());
        assert_eq!(event["generation"], 1);
    }
}

#[test]
fn generation_limit_is_checked_before_publication() {
    let mut recorded = Recorded::default();
    let mut context = session(&mut recorded);
    let first = context.acquire(spec("first")).unwrap();
    context.release(&first).unwrap();
    context.slots[0].generation = MAX_SAFE_INTEGER;
    assert!(matches!(
        context.acquire(spec("same")),
        Err(RunnerError::Pool(_))
    ));
    assert_eq!(recorded.0.len(), 2);
}
