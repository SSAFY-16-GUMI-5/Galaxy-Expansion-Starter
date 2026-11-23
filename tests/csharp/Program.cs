using Galaxy.Runner;

if (args is ["--test"])
    return await RunnerTests.Run();
if (args is ["--catch-failure"])
    return Runner.Run<DemoObject>([], () => new DemoPool(), Demo.CatchFailure, item => item.Snapshot());
return Runner.Run<DemoObject>(args, () => new DemoPool(), Demo.Scenario, item => item.Snapshot());
