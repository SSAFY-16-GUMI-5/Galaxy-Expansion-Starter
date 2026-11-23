package galaxy.fixture;

import galaxy.runner.Runner;
import galaxy.runner.Runner.CosmicSpec;
import galaxy.runner.Runner.Pool;
import galaxy.runner.ScenarioContext;

public final class Demo {
    public static final CosmicSpec FIRST = new CosmicSpec("첫 별 🌟", "seed", "#5dcaff", 1.2);
    public static final CosmicSpec NEXT = new CosmicSpec("Reborn Nova", "planet", "#a78bfa", 1.6);

    private Demo() {}

    public static void main(String[] args) {
        System.exit(Runner.run(args, DemoPool::new, Star::snapshot, Demo::scenario));
    }

    private static void scenario(ScenarioContext<Star> context) {
        System.out.println("Running Java fixture for " + context.participantId());
        var first = context.acquire(FIRST);
        context.release(first);
        var next = context.acquire(NEXT);
        if (!context.snapshot(next).equals(NEXT)) throw new AssertionError("Stale data");
    }

    public static final class Star {
        private CosmicSpec data;

        public CosmicSpec snapshot() { return data; }
    }

    public static final class DemoPool implements Pool<Star> {
        private final Star storage = new Star();
        private boolean borrowed;

        @Override
        public Star acquire(CosmicSpec spec) {
            if (borrowed) throw new IllegalStateException("Demo pool is full");
            storage.data = spec;
            borrowed = true;
            return storage;
        }

        @Override
        public void release(Star star) {
            if (star != storage || !borrowed) throw new IllegalArgumentException("Invalid return");
            borrowed = false;
        }
    }
}
