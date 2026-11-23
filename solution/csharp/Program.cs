using Galaxy.Runner;

return Runner.Run<CosmicObject>(args, () => new ObjectPool(), RunScenario, item => item.Snapshot());

static void RunScenario(IScenarioContext context)
{
    // TODO: Drive an acquire, release and re-acquire through the scenario context.
    throw new NotImplementedException("Implement the participant scenario");
}

internal sealed class CosmicObject
{
    // TODO: Add the four display fields and any other state your object needs.
    public CosmicSpec Snapshot()
    {
        // TODO: Return a value snapshot of this object's current fields.
        throw new NotImplementedException("Implement CosmicObject.Snapshot");
    }
}

internal sealed class ObjectPool : IObjectPool<CosmicObject>
{
    // TODO: Choose how to store available objects and track outstanding borrows.
    public CosmicObject Acquire(CosmicSpec spec)
    {
        // TODO: Borrow storage and initialize every field from spec.
        throw new NotImplementedException("Implement ObjectPool.Acquire");
    }

    public void Release(CosmicObject storage)
    {
        // TODO: Validate ownership and return the borrowed storage to the pool.
        throw new NotImplementedException("Implement ObjectPool.Release");
    }
}
