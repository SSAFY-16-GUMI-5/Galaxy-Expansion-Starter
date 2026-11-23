package galaxy.runner;

import java.util.ArrayList;
import java.util.List;

import galaxy.fixture.Demo;
import galaxy.fixture.Demo.DemoPool;
import galaxy.fixture.Demo.Star;
import galaxy.runner.Runner.CosmicSpec;
import galaxy.runner.Runner.Lease;
import galaxy.runner.Runner.Pool;
import galaxy.runner.Runner.PoolException;
import galaxy.runner.Runner.TransportException;
import galaxy.runner.Runner.UsageException;

public final class RunnerTests {
    private record Notice(String action, String slot, long generation, CosmicSpec data) {}

    public static void main(String[] args) {
        testDomain();
        testLeases();
        testEqualStorage();
        testFatalPoolFailures();
        testTransportFailure();
        testSlotLimit();
        System.out.println("Java identity and lifecycle tests passed");
    }

    private static void testDomain() {
        var pool = new DemoPool();
        var first = pool.acquire(Demo.FIRST);
        expect(IllegalStateException.class, () -> pool.acquire(Demo.NEXT));
        expect(IllegalArgumentException.class, () -> pool.release(new Star()));
        pool.release(first);
        expect(IllegalArgumentException.class, () -> pool.release(first));
        var next = pool.acquire(Demo.NEXT);
        check(first == next && next.snapshot().equals(Demo.NEXT), "Domain must reuse and refresh storage");
    }

    private static void testLeases() {
        var calls = new ArrayList<String>();
        var notices = new ArrayList<Notice>();
        var pool = new DemoPool();
        Pool<Star> observedPool = new Pool<>() {
            public Star acquire(CosmicSpec spec) { calls.add("borrow"); return pool.acquire(spec); }
            public void release(Star star) { calls.add("return"); pool.release(star); }
        };
        var context = new ScenarioContext<>("test", observedPool, star -> {
            calls.add("snapshot");
            return star.snapshot();
        }, (action, slot, generation, data) -> {
            calls.add(action);
            notices.add(new Notice(action, slot, generation, data));
        });
        var foreignContext = new ScenarioContext<>("test", new DemoPool(), Star::snapshot,
            (action, slot, generation, data) -> {});
        var foreign = foreignContext.acquire(Demo.FIRST);
        expect(UsageException.class, () -> context.acquire(new CosmicSpec("\u00a0\ufeff", "seed", "#123456", 1)));
        expect(UsageException.class, () -> context.acquire(new CosmicSpec("\ud800", "seed", "#123456", 1)));
        expect(UsageException.class, () -> context.acquire(new CosmicSpec("a", "seed", "#123456", Double.NaN)));
        Lease first = context.acquire(Demo.FIRST);
        expect(UsageException.class, () -> context.release(foreign));
        CosmicSpec historical = context.snapshot(first);
        context.release(first);
        expect(UsageException.class, () -> context.release(first));
        var next = context.acquire(Demo.NEXT);
        expect(UsageException.class, () -> context.release(first));
        expect(UsageException.class, () -> context.snapshot(new Lease()));
        check(next != first && historical.equals(Demo.FIRST) && context.snapshot(next).equals(Demo.NEXT),
            "Each borrow needs its own lease and snapshot");
        check(notices.equals(List.of(new Notice("acquire", "1", 1, Demo.FIRST),
            new Notice("release", "1", 1, null), new Notice("acquire", "1", 2, Demo.NEXT))),
            "Rejected calls must not emit additional events");
        check(calls.equals(List.of("borrow", "snapshot", "acquire", "return", "release", "borrow",
            "snapshot", "acquire")), "Pool calls must precede publication");
        context.close();
        expect(UsageException.class, () -> context.snapshot(next));
    }

    private record Value(CosmicSpec spec) {}

    private static void testEqualStorage() {
        var notices = new ArrayList<Notice>();
        var context = new ScenarioContext<>("test", new ValuePool(), Value::spec,
            (action, slot, generation, data) -> notices.add(new Notice(action, slot, generation, data)));
        context.acquire(Demo.FIRST);
        context.acquire(Demo.FIRST);
        check(notices.equals(List.of(new Notice("acquire", "1", 1, Demo.FIRST),
            new Notice("acquire", "2", 1, Demo.FIRST))), "Equal values must get distinct slots");
    }

    private static void testFatalPoolFailures() {
        var notices = new ArrayList<Notice>();
        var calls = new ArrayList<String>();
        ScenarioContext.Events events = (action, slot, generation, data) ->
            notices.add(new Notice(action, slot, generation, data));
        var aliased = new Value(Demo.FIRST);
        var aliasContext = new ScenarioContext<>("test", new ValuePool() {
            public Value acquire(CosmicSpec spec) { return aliased; }
            public void release(Value value) { calls.add("return"); }
        }, Value::spec, events);
        aliasContext.acquire(Demo.FIRST);
        expect(PoolException.class, () -> aliasContext.acquire(Demo.FIRST));
        expect(PoolException.class, aliasContext::finish);
        check(calls.isEmpty() && notices.size() == 1, "Never return or publish an active alias");

        var wrongProjection = new ScenarioContext<>("test", new ValuePool() {
            public void release(Value storage) { calls.add("return"); }
        }, value -> Demo.NEXT, events);
        expect(PoolException.class, () -> wrongProjection.acquire(Demo.FIRST));
        expect(PoolException.class, wrongProjection::finish);
        check(calls.equals(List.of("return")) && notices.size() == 1, "Clean up a failed new borrow once");

        var throwingPool = new ScenarioContext<>("test", new ValuePool() {
            public void release(Value storage) { throw new IllegalStateException("release failed"); }
        }, Value::spec, events);
        var lease = throwingPool.acquire(Demo.FIRST);
        expect(PoolException.class, () -> throwingPool.release(lease));
        expect(PoolException.class, () -> throwingPool.acquire(Demo.FIRST));
        check(notices.size() == 2, "Thrown release must stop all publication");

        var throwingAcquire = new ScenarioContext<>("test", new ValuePool() {
            public Value acquire(CosmicSpec spec) { throw new IllegalStateException("acquire failed"); }
        }, Value::spec, events);
        expect(PoolException.class, () -> throwingAcquire.acquire(Demo.FIRST));
        expect(PoolException.class, throwingAcquire::finish);
        check(notices.size() == 2, "Thrown acquire must produce no event");
    }

    private static void testTransportFailure() {
        var pool = new DemoPool();
        var attempts = new ArrayList<String>();
        var context = new ScenarioContext<>("test", pool, Star::snapshot, (action, slot, generation, data) -> {
            attempts.add(action);
            throw new TransportException("Host stopped responding", null);
        });
        expect(TransportException.class, () -> context.acquire(Demo.FIRST));
        expect(TransportException.class, () -> context.acquire(Demo.NEXT));
        expect(TransportException.class, context::finish);
        expect(IllegalStateException.class, () -> pool.acquire(Demo.NEXT));
        check(attempts.equals(List.of("acquire")), "Uncertain publication must not retry or return storage");
    }

    private static void testSlotLimit() {
        var notices = new ArrayList<Notice>();
        var context = new ScenarioContext<>("test", new ValuePool(), Value::spec,
            (action, slot, generation, data) -> notices.add(new Notice(action, slot, generation, data)));
        for (int slot = 0; slot < 500; slot++) context.release(context.acquire(Demo.FIRST));
        expect(PoolException.class, () -> context.acquire(Demo.FIRST));
        check(notices.size() == 1000, "A 501st distinct slot must not publish");
    }

    private static class ValuePool implements Pool<Value> {
        public Value acquire(CosmicSpec spec) { return new Value(spec); }
        public void release(Value storage) {}
    }

    private static void check(boolean condition, String message) {
        if (!condition) throw new AssertionError(message);
    }

    private static void expect(Class<? extends RuntimeException> type, Runnable action) {
        try {
            action.run();
        } catch (RuntimeException failure) {
            if (type.isInstance(failure)) return;
            throw new AssertionError("Expected " + type.getSimpleName(), failure);
        }
        throw new AssertionError("Expected " + type.getSimpleName());
    }
}
