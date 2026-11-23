package galaxy.runner;

import java.io.FileDescriptor;
import java.io.FileOutputStream;
import java.util.function.Consumer;
import java.util.function.Function;
import java.util.function.Supplier;

/** Process entry point for a single, synchronous participant scenario. */
public final class Runner {
    static final long MAX_SAFE_INTEGER = 9_007_199_254_740_991L;

    private Runner() {}

    public record CosmicSpec(String name, String type, String color, double size) {}

    public interface Pool<T> {
        T acquire(CosmicSpec spec);
        void release(T storage);
    }

    public static final class Lease {
        Lease() {}
    }

    public static final class UsageException extends IllegalArgumentException {
        UsageException(String message) { super(message); }
    }

    public static final class PoolException extends IllegalStateException {
        PoolException(String message, Throwable cause) { super(message, cause); }
    }

    public static final class TransportException extends IllegalStateException {
        TransportException(String message, Throwable cause) { super(message, cause); }
    }

    /** Call from main and pass the returned exit code to System.exit. */
    public static <T> int run(String[] args, Supplier<? extends Pool<T>> createPool,
                              Function<T, CosmicSpec> projection,
                              Consumer<ScenarioContext<T>> scenario) {
        if (args.length > 1 || (args.length == 1 && !args[0].equals("--reset-on-start"))) {
            System.err.println("Usage: java -cp <classpath> <participant-main> [--reset-on-start]");
            return 2;
        }

        // Keep diagnostics from participant code off the protocol stream.
        var output = new FileOutputStream(FileDescriptor.out);
        System.setOut(System.err);
        try {
            var transport = new JsonlTransport(System.in, output);
            String participantId = transport.init();
            if (args.length == 1) {
                transport.exchange("reset", null, 0, null);
            }
            var context = new ScenarioContext<T>(participantId, createPool.get(), projection, transport);
            try {
                scenario.accept(context);
                context.finish();
            } finally {
                context.close();
            }
            return 0;
        } catch (RuntimeException failure) {
            failure.printStackTrace(System.err);
            return 1;
        }
    }
}
