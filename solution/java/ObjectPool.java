package galaxy.solution;

import galaxy.runner.Runner.CosmicSpec;
import galaxy.runner.Runner.Pool;

final class ObjectPool implements Pool<CosmicObject> {
    @Override
    public CosmicObject acquire(CosmicSpec spec) {
        // TODO: Choose available storage or allocate under the pool's capacity policy.
        // TODO: Initialize the storage with spec and mark it borrowed before returning it.
        throw new UnsupportedOperationException("Implement acquire");
    }

    @Override
    public void release(CosmicObject storage) {
        // TODO: Reject foreign or inactive storage by reference identity.
        // TODO: Make the returned storage available for reuse.
        throw new UnsupportedOperationException("Implement release");
    }
}
