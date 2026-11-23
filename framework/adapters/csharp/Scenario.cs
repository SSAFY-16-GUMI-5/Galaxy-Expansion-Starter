using System.Globalization;
using System.Text;
using System.Text.RegularExpressions;

namespace Galaxy.Runner;

public sealed record CosmicSpec(string Name, string Type, string Color, double Size);

public interface IObjectPool<T> where T : class
{
    T Acquire(CosmicSpec spec);
    void Release(T storage);
}

public sealed class Lease
{
    internal Lease() { }
}

public interface IScenarioContext
{
    string ParticipantId { get; }
    Lease Acquire(CosmicSpec spec);
    CosmicSpec Snapshot(Lease lease);
    void Release(Lease lease);
}

public sealed class RunnerUsageException(string message) : InvalidOperationException(message);
public sealed class PoolOperationException(string message, Exception inner) : InvalidOperationException(message, inner);
public sealed class RunnerTransportException(string message, Exception? inner = null) : IOException(message, inner);

internal sealed class ScenarioContext<T>(
    string participantId,
    IObjectPool<T> pool,
    Func<T, CosmicSpec> project,
    Action<object, string, string> send,
    Action checkTransport) : IScenarioContext where T : class
{
    private sealed class Slot(string id)
    {
        public string Id { get; } = id;
        public long Generation { get; set; }
        public bool Active { get; set; }
    }

    private sealed record Borrow(T Storage, Slot Slot, CosmicSpec Snapshot);

    private readonly Dictionary<T, Slot> slots = new(ReferenceEqualityComparer.Instance);
    private readonly Dictionary<Lease, Borrow> active = new();
    private readonly int ownerThread = Environment.CurrentManagedThreadId;
    private Exception? failure;
    private bool busy;
    private bool closed;

    public string ParticipantId { get; } = participantId;

    public Lease Acquire(CosmicSpec spec)
    {
        CheckUsable();
        if (!Valid(spec))
            throw new RunnerUsageException("Invalid cosmic specification");

        busy = true;
        try
        {
            T storage = pool.Acquire(spec) ?? throw new InvalidOperationException("Pool returned null storage");
            slots.TryGetValue(storage, out Slot? slot);
            if (slot?.Active == true)
                throw new InvalidOperationException("Pool returned already active storage");

            CosmicSpec captured;
            try
            {
                if (slot is null && slots.Count >= 500)
                    throw new InvalidOperationException("Participant slot limit (500) exceeded");
                if (slot?.Generation == JsonlTransport.MaxSafeInteger)
                    throw new InvalidOperationException("Generation limit exceeded");
                captured = project(storage);
                if (!Valid(captured) || captured != spec)
                    throw new InvalidOperationException("Storage snapshot does not match the requested fields");
            }
            catch
            {
                // This borrow has not been published and does not alias an active borrow.
                try { pool.Release(storage); }
                catch (Exception) { /* Preserve the original failure. */ }
                throw;
            }

            if (slot is null)
            {
                slot = new Slot((slots.Count + 1).ToString(CultureInfo.InvariantCulture));
                slots.Add(storage, slot);
            }
            slot.Generation++;
            slot.Active = true;
            var lease = new Lease();
            active.Add(lease, new Borrow(storage, slot, captured));
            Publish(new { type = "acquire", poolSlotId = slot.Id, slot.Generation, data = captured },
                "acquire", slot);
            return lease;
        }
        catch (Exception error)
        {
            throw Fail("acquire", error);
        }
        finally { busy = false; }
    }

    public CosmicSpec Snapshot(Lease lease)
    {
        CheckUsable();
        return GetBorrow(lease).Snapshot;
    }

    public void Release(Lease lease)
    {
        CheckUsable();
        Borrow borrow = GetBorrow(lease);
        Slot slot = borrow.Slot;
        busy = true;
        try
        {
            pool.Release(borrow.Storage);
            active.Remove(lease);
            slot.Active = false;
            Publish(new { type = "release", poolSlotId = slot.Id, slot.Generation }, "release", slot);
        }
        catch (Exception error)
        {
            throw Fail($"release slot {slot.Id} generation {slot.Generation}", error);
        }
        finally { busy = false; }
    }

    internal void Complete()
    {
        ThrowIfFailed();
        checkTransport();
    }

    internal void Close() => closed = true;

    private void CheckUsable()
    {
        if (Environment.CurrentManagedThreadId != ownerThread || closed || busy)
            throw new RunnerUsageException("Use the scenario context synchronously during its run");
        Complete();
    }

    private void ThrowIfFailed()
    {
        if (failure is not null)
            System.Runtime.ExceptionServices.ExceptionDispatchInfo.Throw(failure);
    }

    private Borrow GetBorrow(Lease lease) =>
        lease is not null && active.TryGetValue(lease, out Borrow? borrow)
            ? borrow
            : throw new RunnerUsageException("Expected an active lease issued by this session");

    private void Publish(object payload, string action, Slot slot)
    {
        try { send(payload, action, $"{action} slot {slot.Id} generation {slot.Generation}"); }
        catch (RunnerTransportException error)
        {
            failure = error;
            throw;
        }
    }

    private Exception Fail(string operation, Exception error) =>
        failure ??= new PoolOperationException($"{operation}: {error.Message}", error);

    private static bool Valid(CosmicSpec? spec)
    {
        if (spec?.Name is not { Length: > 0 and <= 40 } name ||
            !name.Any(character => !IsEcmaWhitespace(character)) ||
            spec.Type is not ("seed" or "star" or "planet") ||
            spec.Color is not { Length: 7 } color || !Regex.IsMatch(color, @"\A#[0-9a-fA-F]{6}\z") ||
            !double.IsFinite(spec.Size) || spec.Size is < 0.3 or > 3.5)
            return false;
        try { JsonlTransport.Utf8.GetByteCount(name); }
        catch (EncoderFallbackException) { return false; }
        return true;
    }

    private static bool IsEcmaWhitespace(char character) => character is
        >= '\u0009' and <= '\u000D' or '\u0020' or '\u00A0' or '\u1680' or
        >= '\u2000' and <= '\u200A' or '\u2028' or '\u2029' or '\u202F' or
        '\u205F' or '\u3000' or '\uFEFF';
}
