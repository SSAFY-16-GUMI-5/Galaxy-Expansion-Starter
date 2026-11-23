using Galaxy.Runner;

internal static class Demo
{
    internal static readonly CosmicSpec First = new("오로라 ✨", "star", "#5dcaff", 1.2);
    internal static readonly CosmicSpec Second = new("새로운 행성", "planet", "#a78bfa", 1.6);

    public static void Scenario(IScenarioContext context)
    {
        Console.WriteLine($"Demo for {context.ParticipantId}");
        Lease first = context.Acquire(First);
        context.Release(first);
        Lease second = context.Acquire(Second);
        if (context.Snapshot(second) != Second)
            throw new InvalidOperationException("Reused storage has stale fields");
    }

    public static void CatchFailure(IScenarioContext context)
    {
        try { context.Acquire(First); }
        catch (RunnerTransportException) { }
        try { context.Acquire(Second); }
        catch (RunnerTransportException) { }
    }
}

internal sealed class DemoObject
{
    public string Name = "";
    public string Type = "";
    public string Color = "";
    public double Size;

    public CosmicSpec Snapshot() => new(Name, Type, Color, Size);

    // Deliberately make equal-valued storage compare equal in the identity tests.
    public override bool Equals(object? other) => other is DemoObject item && Snapshot() == item.Snapshot();
    public override int GetHashCode() => Snapshot().GetHashCode();
}

internal sealed class DemoPool : IObjectPool<DemoObject>
{
    private readonly DemoObject storage = new();
    private bool borrowed;

    public DemoObject Acquire(CosmicSpec spec)
    {
        if (borrowed)
            throw new InvalidOperationException("Fixture pool is full");
        storage.Name = spec.Name;
        storage.Type = spec.Type;
        storage.Color = spec.Color;
        storage.Size = spec.Size;
        borrowed = true;
        return storage;
    }

    public void Release(DemoObject item)
    {
        if (!ReferenceEquals(storage, item) || !borrowed)
            throw new InvalidOperationException("Fixture storage is not borrowed from this pool");
        borrowed = false;
    }
}
