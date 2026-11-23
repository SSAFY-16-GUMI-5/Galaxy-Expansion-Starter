using System.Diagnostics;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Galaxy.Runner;

internal sealed class JsonlTransport : IDisposable
{
    internal const long MaxSafeInteger = 9_007_199_254_740_991;
    internal static readonly UTF8Encoding Utf8 = new(false, true);
    private const int MaxLineBytes = 8_000;
    private static readonly TimeSpan SendInterval = TimeSpan.FromMilliseconds(25);
    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.CamelCase
    };

    private readonly object gate = new();
    private readonly Stream output;
    private readonly long started = Stopwatch.GetTimestamp();
    private long? pendingSince;
    private (string Line, long Received)? reply;
    private long? lastSend;
    private string? fault;
    private bool eof;
    private bool closed;

    public JsonlTransport(Stream input, Stream output)
    {
        this.output = output;
        pendingSince = started;
        new Thread(() => ReadLines(input)) { IsBackground = true, Name = "Galaxy stdin reader" }.Start();
    }

    public string ReadInit(TimeSpan timeout)
    {
        using var document = ReadObject("init", started, timeout);
        JsonElement root = document.RootElement;
        string? id = StringProperty(root, "participantId");
        if (StringProperty(root, "type") != "init" || id is null ||
            !Regex.IsMatch(id, @"\A[A-Za-z0-9_-]{1,32}\z"))
            throw new RunnerTransportException("init: expected init with a valid participantId");
        return id;
    }

    public void Exchange(object payload, string action, string phase, TimeSpan timeout)
    {
        byte[] line = JsonSerializer.SerializeToUtf8Bytes(payload, JsonOptions);
        if (line.Length > MaxLineBytes)
            throw new RunnerTransportException($"{phase}: event exceeds 8000 UTF-8 bytes");
        Array.Resize(ref line, line.Length + 1);
        line[^1] = (byte)'\n';

        if (lastSend is long previous)
        {
            TimeSpan remaining;
            while ((remaining = SendInterval - Stopwatch.GetElapsedTime(previous)) > TimeSpan.Zero)
                Thread.Sleep((int)Math.Ceiling(remaining.TotalMilliseconds));
        }

        long sent;
        lock (gate)
        {
            CheckFault(phase);
            if (eof)
                throw new RunnerTransportException($"{phase}: stdin reached EOF before sending");
            pendingSince = Stopwatch.GetTimestamp();
            try
            {
                output.Write(line);
                output.Flush();
            }
            catch (IOException error)
            {
                throw new RunnerTransportException($"{phase}: stdout write failed: {error.Message}", error);
            }
            lastSend = sent = Stopwatch.GetTimestamp();
        }

        using var document = ReadObject($"{phase} ack", sent, timeout);
        JsonElement root = document.RootElement;
        string? type = StringProperty(root, "type");
        if (type == "error" && StringProperty(root, "message") is string reason)
            throw new RunnerTransportException($"{phase}: remote rejection: {JsonSerializer.Serialize(reason)}");
        if (type != "ack" || StringProperty(root, "action") != action ||
            !root.TryGetProperty("revision", out JsonElement revision) || revision.ValueKind != JsonValueKind.Number ||
            !revision.TryGetDouble(out double number) || number < 1 || number > MaxSafeInteger ||
            number != Math.Truncate(number))
            throw new RunnerTransportException($"{phase}: expected matching ack with a valid revision");
    }

    public void CheckIdle()
    {
        lock (gate)
            CheckFault("idle");
    }

    public void Dispose()
    {
        lock (gate)
            closed = true;
    }

    private void ReadLines(Stream input)
    {
        var buffer = new byte[4096];
        var line = new byte[MaxLineBytes + 1]; // Extra byte for CR before LF.
        int length = 0;
        try
        {
            while (true)
            {
                int count = input.Read(buffer);
                long received = Stopwatch.GetTimestamp();
                lock (gate)
                {
                    if (closed || fault is not null)
                        return;
                    for (int i = 0; i < count && fault is null; i++)
                    {
                        byte value = buffer[i];
                        if (pendingSince is not long start || received < start || reply is not null)
                            fault = "unsolicited control message";
                        else if (value == '\n')
                        {
                            int size = length > 0 && line[length - 1] == '\r' ? length - 1 : length;
                            reply = (Utf8.GetString(line, 0, size), received);
                            length = 0;
                        }
                        else if (length < MaxLineBytes || (length == MaxLineBytes && value == '\r'))
                            line[length++] = value;
                        else
                            fault = "JSONL input exceeds 8000 bytes";
                    }
                    eof = count == 0;
                    if (eof && length != 0)
                        fault = "unterminated JSONL input at EOF";
                    Monitor.PulseAll(gate);
                    if (eof || fault is not null)
                        return;
                }
            }
        }
        catch (Exception error) when (error is IOException or DecoderFallbackException or ObjectDisposedException)
        {
            lock (gate)
            {
                fault = $"stdin read failed: {error.Message}";
                Monitor.PulseAll(gate);
            }
        }
    }

    private JsonDocument ReadObject(string phase, long since, TimeSpan timeout)
    {
        string line;
        lock (gate)
        {
            while (true)
            {
                CheckFault(phase);
                if (reply is { } received)
                {
                    if (Stopwatch.GetElapsedTime(since, received.Received) > timeout)
                        throw new RunnerTransportException($"{phase}: timed out");
                    line = received.Line;
                    reply = null;
                    pendingSince = null;
                    break;
                }
                if (eof)
                    throw new RunnerTransportException($"{phase}: stdin reached EOF");
                TimeSpan remaining = timeout - Stopwatch.GetElapsedTime(since);
                if (remaining <= TimeSpan.Zero)
                    throw new RunnerTransportException($"{phase}: timed out");
                Monitor.Wait(gate, remaining);
            }
        }

        JsonDocument document;
        try { document = JsonDocument.Parse(line); }
        catch (JsonException error)
        {
            throw new RunnerTransportException($"{phase}: invalid JSON: {error.Message}", error);
        }
        if (document.RootElement.ValueKind == JsonValueKind.Object)
            return document;
        document.Dispose();
        throw new RunnerTransportException($"{phase}: expected a JSON object");
    }

    private void CheckFault(string phase)
    {
        if (fault is not null)
            throw new RunnerTransportException($"{phase}: {fault}");
    }

    private static string? StringProperty(JsonElement element, string key) =>
        element.TryGetProperty(key, out JsonElement value) && value.ValueKind == JsonValueKind.String
            ? ReadString(value)
            : null;

    private static string? ReadString(JsonElement value)
    {
        try { return value.GetString(); }
        catch (InvalidOperationException) { return null; } // Unpaired escaped surrogate.
    }
}
