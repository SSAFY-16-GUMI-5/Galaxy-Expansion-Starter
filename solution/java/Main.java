package galaxy.solution;

import galaxy.runner.Runner;
import galaxy.runner.ScenarioContext;

public final class Main {
    private Main() {}

    public static void main(String[] args) {
        System.exit(Runner.run(args, ObjectPool::new, CosmicObject::snapshot, Main::scenario));
    }

    private static void scenario(ScenarioContext<CosmicObject> context) {
        // TODO: Acquire a lease, inspect its snapshot, and release it.
        // TODO: Acquire the same storage with a different spec, then check the new snapshot.
        throw new UnsupportedOperationException("Implement the participant scenario");
    }
}
