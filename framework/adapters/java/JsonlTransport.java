package galaxy.runner;

import java.io.BufferedInputStream;
import java.io.EOFException;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.ByteBuffer;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;

import com.google.gson.Gson;
import com.google.gson.GsonBuilder;
import com.google.gson.JsonObject;
import com.google.gson.Strictness;

import galaxy.runner.Runner.CosmicSpec;
import galaxy.runner.Runner.TransportException;
import galaxy.runner.ScenarioContext.Events;

final class JsonlTransport implements Events {
    private static final int MAX_LINE_BYTES = 8_000;
    private static final long INTERVAL = TimeUnit.MILLISECONDS.toNanos(25);
    private static final long INIT_TIMEOUT = TimeUnit.SECONDS.toNanos(5);
    private static final long ACK_TIMEOUT = TimeUnit.SECONDS.toNanos(2);
    private static final Pattern PARTICIPANT = Pattern.compile("[A-Za-z0-9_-]{1,32}");
    private static final Gson JSON = new GsonBuilder().setStrictness(Strictness.STRICT).create();

    private final OutputStream output;
    private final Object monitor = new Object();
    // At most one received line is retained. The reader may block even during JVM shutdown.
    private boolean expecting = true;
    private String received;
    private long receivedAt;
    private IOException fault;
    private boolean sent;
    private long lastSent;

    JsonlTransport(InputStream input, OutputStream output) {
        this.output = output;
        Thread.ofPlatform().daemon().name("galaxy-stdin").start(() -> readLines(input));
    }

    String init() {
        String phase = "init";
        JsonObject message = readObject(phase, System.nanoTime() + INIT_TIMEOUT);
        String id = string(message, "participantId");
        if (!"init".equals(string(message, "type")) || id == null || !PARTICIPANT.matcher(id).matches()) {
            throw failure(phase, "Expected init with a valid participantId", null);
        }
        return id;
    }

    @Override
    public void exchange(String action, String slot, long generation, CosmicSpec snapshot) {
        String phase = slot == null ? action : action + " slot " + slot + " generation " + generation;
        var event = new JsonObject();
        event.addProperty("type", action);
        if (slot != null) {
            event.addProperty("poolSlotId", slot);
            event.addProperty("generation", generation);
        }
        if (snapshot != null) event.add("data", JSON.toJsonTree(snapshot));
        byte[] line = (JSON.toJson(event) + "\n").getBytes(StandardCharsets.UTF_8);
        if (line.length - 1 > MAX_LINE_BYTES) {
            throw failure(phase, "Event exceeds 8000 UTF-8 bytes", null);
        }

        long deadline;
        try {
            if (sent) {
                long remaining;
                while ((remaining = INTERVAL - (System.nanoTime() - lastSent)) > 0) {
                    TimeUnit.NANOSECONDS.sleep(remaining);
                }
            }
            synchronized (monitor) {
                checkFault(phase, false);
                expecting = true;
                deadline = System.nanoTime() + ACK_TIMEOUT;
            }
            output.write(line);
            output.flush();
            lastSent = System.nanoTime();
            sent = true;
        } catch (IOException cause) {
            throw failure(phase, "Cannot write stdout", cause);
        } catch (InterruptedException cause) {
            Thread.currentThread().interrupt();
            throw failure(phase, "Interrupted before publication", cause);
        }

        JsonObject reply = readObject(phase, deadline);
        String type = string(reply, "type");
        String message = string(reply, "message");
        if ("error".equals(type) && message != null) {
            throw failure(phase, "Rejected by host: " + message, null);
        }
        if (!"ack".equals(type) || !action.equals(string(reply, "action")) || !validRevision(reply)) {
            throw failure(phase, "Expected matching ack with a positive safe-integer revision", null);
        }
    }

    @Override
    public void checkIdle(boolean finishing) {
        synchronized (monitor) {
            checkFault("idle", finishing);
        }
    }

    private void readLines(InputStream input) {
        var buffered = new BufferedInputStream(input);
        var bytes = new byte[MAX_LINE_BYTES + 1]; // Allow a final CR before LF.
        int length = 0;
        try {
            for (int next; (next = buffered.read()) != -1;) {
                if (next == '\n') {
                    int payloadLength = length;
                    if (length > 0 && bytes[length - 1] == '\r') payloadLength--;
                    if (payloadLength > MAX_LINE_BYTES) throw new IOException("stdin line exceeds 8000 bytes");
                    String line = StandardCharsets.UTF_8.newDecoder()
                        .decode(ByteBuffer.wrap(bytes, 0, payloadLength)).toString();
                    synchronized (monitor) {
                        if (!expecting) throw new IOException("Unsolicited control message");
                        expecting = false;
                        received = line;
                        receivedAt = System.nanoTime();
                        monitor.notifyAll();
                    }
                    length = 0;
                } else {
                    if (length == bytes.length) throw new IOException("stdin line exceeds 8000 bytes");
                    bytes[length++] = (byte) next;
                }
            }
            if (length != 0) throw new IOException("Incomplete JSONL line at stdin EOF");
            throw new EOFException("stdin closed");
        } catch (IOException cause) {
            synchronized (monitor) {
                fault = cause;
                monitor.notifyAll();
            }
        }
    }

    private JsonObject readObject(String phase, long deadline) {
        String line;
        try {
            synchronized (monitor) {
                while (received == null) {
                    checkFault(phase, false);
                    long remaining = deadline - System.nanoTime();
                    if (remaining <= 0) throw failure(phase, "Timed out waiting for stdin", null);
                    TimeUnit.NANOSECONDS.timedWait(monitor, remaining);
                }
                checkFault(phase, true);
                if (receivedAt - deadline > 0) throw failure(phase, "Timed out waiting for stdin", null);
                line = received;
                received = null;
            }
        } catch (InterruptedException cause) {
            Thread.currentThread().interrupt();
            throw failure(phase, "Interrupted while reading stdin", cause);
        }

        try {
            JsonObject parsed = JSON.fromJson(line, JsonObject.class);
            if (parsed != null) return parsed;
        } catch (RuntimeException cause) {
            throw failure(phase, "Malformed JSON object on stdin", cause);
        }
        throw failure(phase, "Expected JSON object on stdin", null);
    }

    private void checkFault(String phase, boolean allowEof) {
        if (fault != null && !(allowEof && fault instanceof EOFException)) {
            throw failure(phase, "Invalid control stream: " + fault.getMessage(), fault);
        }
    }

    private static String string(JsonObject object, String key) {
        var value = object.get(key);
        return value != null && value.isJsonPrimitive() && value.getAsJsonPrimitive().isString()
            ? value.getAsString() : null;
    }

    private static boolean validRevision(JsonObject reply) {
        var revision = reply.get("revision");
        if (revision == null || !revision.isJsonPrimitive() || !revision.getAsJsonPrimitive().isNumber()) {
            return false;
        }
        double value = revision.getAsDouble();
        return value >= 1 && value <= Runner.MAX_SAFE_INTEGER && value == Math.rint(value);
    }

    private static TransportException failure(String phase, String message, Throwable cause) {
        return new TransportException(phase + ": " + message, cause);
    }
}
