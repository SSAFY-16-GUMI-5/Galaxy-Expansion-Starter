using System.Diagnostics;
using System.Text.Json;
using Galaxy.Runner;

internal static class RunnerTests
{
    private const string Init = "{\"type\":\"init\",\"participantId\":\"csharp-test\"}\r\n";

    internal static async Task<int> Run()
    {
        try
        {
            IdentityAndLeases();
            LocalFailures();
            await SuccessfulRun(reset: false);
            await SuccessfulRun(reset: true);
            await FailingRun("mismatched ack", Ack("release", 1), "expected matching ack");
            await FailingRun("rejection", "{\"type\":\"error\",\"message\":\"denied\"}\n", "denied",
                "--catch-failure");
            await FailingRun("invalid revision", Ack("acquire", 9_007_199_254_740_992), "valid revision");
            await FailingRun("malformed JSON", "{\n", "invalid JSON");
            await FailingRun("oversized reply", new string(' ', 8_001), "exceeds 8000");
            await FailingRun("timeout", null, "timed out");
            await FailingRun("early EOF", null, "stdin reached EOF", closeInput: true);
            await FailingRun("duplicate ack", Ack("acquire", 1) + Ack("acquire", 2), "unsolicited");
            await InvalidInit();
            Console.WriteLine("PASS: C# identity, lifecycle and JSONL subprocess checks");
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine(error);
            return 1;
        }
    }

    private static void IdentityAndLeases()
    {
        var pool = new DemoPool();
        DemoObject firstStorage = pool.Acquire(Demo.First);
        Throws<InvalidOperationException>(() => pool.Acquire(Demo.Second));
        Throws<InvalidOperationException>(() => pool.Release(new DemoObject()));
        pool.Release(firstStorage);
        Throws<InvalidOperationException>(() => pool.Release(firstStorage));
        DemoObject reused = pool.Acquire(Demo.Second);
        Check(ReferenceEquals(firstStorage, reused), "Pool reused its actual storage reference");
        Check(reused.Snapshot() == Demo.Second, "Pool reinitialized all four fields");
        pool.Release(reused);

        List<string> calls = [];
        var observed = new TestPool(
            spec => { calls.Add("borrow"); return pool.Acquire(spec); },
            item => { calls.Add("return"); pool.Release(item); });
        var context = new ScenarioContext<DemoObject>("test", observed,
            item => { calls.Add("project"); return item.Snapshot(); },
            (_, _, phase) => calls.Add(phase), () => { });
        var foreign = CreateContext(new DemoPool(), []);
        Lease first = context.Acquire(Demo.First);
        CosmicSpec historical = context.Snapshot(first);
        Throws<RunnerUsageException>(() => foreign.Release(first));
        Throws<RunnerUsageException>(() => context.Release(new Lease()));
        context.Release(first);
        Throws<RunnerUsageException>(() => context.Release(first));
        Lease second = context.Acquire(Demo.Second);
        Throws<RunnerUsageException>(() => context.Snapshot(first));
        Throws<RunnerUsageException>(() => context.Release(first));
        Check(historical == Demo.First && context.Snapshot(second) == Demo.Second, "Snapshots by lease");
        context.Release(second);
        Check(calls.SequenceEqual(new[] {
            "borrow", "project", "acquire slot 1 generation 1", "return", "release slot 1 generation 1",
            "borrow", "project", "acquire slot 1 generation 2", "return", "release slot 1 generation 2"
        }), "Domain call order and no calls for rejected leases");
        context.Close();
        Throws<RunnerUsageException>(() => context.Acquire(Demo.First));

        DemoObject equalA = MakeStorage(Demo.First);
        DemoObject equalB = MakeStorage(Demo.First);
        Check(equalA.Equals(equalB), "Fixture storage compares equal by value");
        var values = new Queue<DemoObject>([equalA, equalB]);
        List<string> events = [];
        var distinct = CreateContext(new TestPool(_ => values.Dequeue(), _ => { }), events);
        distinct.Acquire(Demo.First);
        distinct.Acquire(Demo.First);
        Check(events.SequenceEqual(new[] { "acquire slot 1 generation 1", "acquire slot 2 generation 1" }),
            "Equal-valued references retain distinct slots");
    }

    private static void LocalFailures()
    {
        List<string> events = [];
        int borrows = 0;
        int returns = 0;
        DemoObject storage = MakeStorage(Demo.First);
        var pool = new TestPool(_ => { borrows++; return storage; }, _ => returns++);
        var alias = CreateContext(pool, events);
        foreach (CosmicSpec invalid in new[] {
            Demo.First with { Name = "\uFEFF\u00A0" }, Demo.First with { Name = "\uD800" },
            Demo.First with { Name = new string('a', 41) }, Demo.First with { Type = "STAR" },
            Demo.First with { Color = "#00000z" }, Demo.First with { Size = double.NaN }
        })
            Throws<RunnerUsageException>(() => alias.Acquire(invalid));
        Check(borrows == 0 && events.Count == 0, "Invalid input did not call the pool");
        alias.Acquire(Demo.First);
        Throws<PoolOperationException>(() => alias.Acquire(Demo.First));
        Throws<PoolOperationException>(alias.Complete);
        Check(borrows == 2 && returns == 0 && events.Count == 1, "Active alias remained borrowed");

        events.Clear();
        var badProjection = CreateContext(pool, events);
        Throws<PoolOperationException>(() => badProjection.Acquire(Demo.Second));
        Check(returns == 1 && events.Count == 0, "Invalid projection cleaned up without publishing");

        var failedAcquire = CreateContext(new TestPool(_ => throw new Exception("borrow failed"), _ => { }), events);
        Throws<PoolOperationException>(() => failedAcquire.Acquire(Demo.First));
        Throws<PoolOperationException>(() => failedAcquire.Acquire(Demo.First));
        Check(events.Count == 0, "Thrown borrow produced no event");
        var failedRelease = CreateContext(new TestPool(MakeStorage, _ => throw new Exception("return failed")), events);
        Lease lease = failedRelease.Acquire(Demo.First);
        Throws<PoolOperationException>(() => failedRelease.Release(lease));
        Throws<PoolOperationException>(failedRelease.Complete);
        Check(events.Count == 1, "Thrown return produced no release event");

        events.Clear();
        var many = CreateContext(new TestPool(MakeStorage, _ => { }), events);
        for (int i = 0; i < 500; i++)
            many.Release(many.Acquire(Demo.First));
        Throws<PoolOperationException>(() => many.Acquire(Demo.First));
        Check(events.Count == 1000, "500 distinct slots allowed and the next slot rejected");
    }

    private static async Task SuccessfulRun(bool reset)
    {
        await InChild(reset ? "--reset-on-start" : null, async (child, token) =>
        {
            await Send(child, Init, token);
            string[] expected = reset ? ["reset", "acquire", "release", "acquire"] : ["acquire", "release", "acquire"];
            string expectedSlot = "1";
            for (int i = 0; i < expected.Length; i++)
            {
                string line = await child.StandardOutput.ReadLineAsync(token) ?? throw new Exception("Expected event");
                using var document = JsonDocument.Parse(line);
                JsonElement item = document.RootElement;
                string action = expected[i];
                Check(item.GetProperty("type").GetString() == action, "Serialized event order");
                Check(!item.TryGetProperty("participantId", out _), "Event omitted participant ID");
                if (action != "reset")
                {
                    Check(item.GetProperty("poolSlotId").GetString() == expectedSlot, "Same string slot");
                    Check(item.GetProperty("generation").GetInt32() == (i == expected.Length - 1 ? 2 : 1),
                        "Expected generation");
                }
                if (action == "acquire")
                {
                    CosmicSpec spec = i == expected.Length - 1 ? Demo.Second : Demo.First;
                    JsonElement data = item.GetProperty("data");
                    Check(data.GetProperty("name").GetString() == spec.Name &&
                        data.GetProperty("type").GetString() == spec.Type &&
                        data.GetProperty("color").GetString() == spec.Color &&
                        data.GetProperty("size").GetDouble() == spec.Size, "Wire snapshot round trips");
                }
                if (i == expected.Length - 1)
                {
                    await Task.Delay(80, token);
                    Check(!child.HasExited, "Child waits for the final ack");
                }
                await Send(child, Ack(action, (i + 1) * 3), token);
            }
            await CheckExit(child, 0, "Demo for csharp-test", token);
        });
    }

    private static async Task FailingRun(string name, string? reply, string diagnostic,
        string? argument = null, bool closeInput = false)
    {
        try
        {
            await InChild(argument, async (child, token) =>
            {
                await Send(child, Init, token);
                Check(await child.StandardOutput.ReadLineAsync(token) is not null, "Expected initial acquire");
                if (reply is not null)
                    await Send(child, reply, token);
                if (closeInput)
                    child.StandardInput.Close();
                await CheckExit(child, 1, diagnostic, token);
            });
        }
        catch (Exception error)
        {
            throw new Exception($"Subprocess case {name} failed", error);
        }
    }

    private static async Task InvalidInit()
    {
        await InChild(null, async (child, token) =>
        {
            await child.StandardInput.BaseStream.WriteAsync(new byte[] { 0xFF, 0x0A }, token);
            await child.StandardInput.BaseStream.FlushAsync(token);
            await CheckExit(child, 1, "stdin read failed", token);
        });
        await InChild(null, async (child, token) =>
        {
            await Send(child, "{\"type\":\"init\",\"participantId\":\"bad id\"}\n", token);
            await CheckExit(child, 1, "valid participantId", token);
        });
    }

    private static async Task InChild(string? argument, Func<Process, CancellationToken, Task> exercise)
    {
        string host = Environment.ProcessPath ?? throw new Exception("No process executable path");
        var start = new ProcessStartInfo(host)
        {
            RedirectStandardInput = true, RedirectStandardOutput = true, RedirectStandardError = true,
            UseShellExecute = false
        };
        if (Path.GetFileNameWithoutExtension(host).Equals("dotnet", StringComparison.OrdinalIgnoreCase))
            start.ArgumentList.Add(typeof(RunnerTests).Assembly.Location);
        if (argument is not null)
            start.ArgumentList.Add(argument);
        using var child = Process.Start(start) ?? throw new Exception("Unable to start child");
        using var deadline = new CancellationTokenSource(TimeSpan.FromSeconds(8));
        try { await exercise(child, deadline.Token); }
        finally
        {
            if (!child.HasExited)
                child.Kill();
        }
    }

    private static async Task CheckExit(Process child, int code, string diagnostic, CancellationToken token)
    {
        string remaining = await child.StandardOutput.ReadToEndAsync(token);
        string stderr = await child.StandardError.ReadToEndAsync(token);
        await child.WaitForExitAsync(token);
        Check(remaining.Length == 0, $"Unexpected additional stdout: {remaining}");
        Check(child.ExitCode == code && stderr.Contains(diagnostic, StringComparison.Ordinal),
            $"Expected exit {code} and '{diagnostic}', got {child.ExitCode}: {stderr}");
    }

    private static async Task Send(Process child, string value, CancellationToken token)
    {
        await child.StandardInput.BaseStream.WriteAsync(JsonlTransport.Utf8.GetBytes(value), token);
        await child.StandardInput.BaseStream.FlushAsync(token);
    }

    private static string Ack(string action, long revision) =>
        JsonSerializer.Serialize(new { type = "ack", action, revision }) + "\n";

    private static ScenarioContext<DemoObject> CreateContext(IObjectPool<DemoObject> pool, List<string> events) =>
        new("test", pool, item => item.Snapshot(), (_, _, phase) => events.Add(phase), () => { });

    private static DemoObject MakeStorage(CosmicSpec spec) =>
        new() { Name = spec.Name, Type = spec.Type, Color = spec.Color, Size = spec.Size };

    private static void Check(bool condition, string message)
    {
        if (!condition)
            throw new Exception(message);
    }

    private static void Throws<T>(Action action) where T : Exception
    {
        try { action(); }
        catch (T) { return; }
        throw new Exception($"Expected {typeof(T).Name}");
    }

    private sealed class TestPool(Func<CosmicSpec, DemoObject> acquire, Action<DemoObject> release)
        : IObjectPool<DemoObject>
    {
        public DemoObject Acquire(CosmicSpec spec) => acquire(spec);
        public void Release(DemoObject storage) => release(storage);
    }
}
