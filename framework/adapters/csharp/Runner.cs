namespace Galaxy.Runner;

public static class Runner
{
    public static int Run<T>(
        string[] args,
        Func<IObjectPool<T>> createPool,
        Action<IScenarioContext> scenario,
        Func<T, CosmicSpec> snapshot) where T : class
    {
        if (args.Length > 1 || (args.Length == 1 && args[0] != "--reset-on-start"))
        {
            Console.Error.WriteLine("Usage: <participant executable> [--reset-on-start]");
            return 1;
        }

        TextWriter originalOutput = Console.Out;
        ConsoleCancelEventHandler cancel = (_, _) => Environment.Exit(130);
        Console.CancelKeyPress += cancel;
        Console.SetOut(Console.Error);
        try
        {
            using var transport = new JsonlTransport(Console.OpenStandardInput(), Console.OpenStandardOutput());
            string participantId = transport.ReadInit(TimeSpan.FromSeconds(5));
            TimeSpan ackTimeout = TimeSpan.FromSeconds(2);
            if (args.Length == 1)
                transport.Exchange(new { type = "reset" }, "reset", "startup reset", ackTimeout);
            transport.CheckIdle();
            IObjectPool<T> pool = createPool() ?? throw new InvalidOperationException("Pool factory returned null");
            var context = new ScenarioContext<T>(participantId, pool, snapshot,
                (payload, action, phase) => transport.Exchange(payload, action, phase, ackTimeout),
                transport.CheckIdle);
            try
            {
                scenario(context);
                context.Complete();
            }
            finally { context.Close(); }
            return 0;
        }
        catch (Exception error)
        {
            Console.Error.WriteLine($"[galaxy runner] {error.GetType().Name}: {error.Message}");
            return 1;
        }
        finally
        {
            Console.SetOut(originalOutput);
            Console.CancelKeyPress -= cancel;
        }
    }
}
