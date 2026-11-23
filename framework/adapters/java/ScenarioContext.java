package galaxy.runner;

import java.nio.charset.StandardCharsets;
import java.util.IdentityHashMap;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.regex.Pattern;

import galaxy.runner.Runner.CosmicSpec;
import galaxy.runner.Runner.Lease;
import galaxy.runner.Runner.Pool;
import galaxy.runner.Runner.PoolException;
import galaxy.runner.Runner.UsageException;

/** Tracks issued leases and observes the pool's actual storage references. */
public final class ScenarioContext<T> {
    private static final int SLOT_LIMIT = 500;
    private static final Set<String> TYPES = Set.of("seed", "star", "planet");
    private static final Pattern COLOR = Pattern.compile("#[0-9a-fA-F]{6}");
    private static final Pattern BLANK_NAME =
        Pattern.compile("[\\p{Zs}\\t\\n\\u000B\\f\\r\\u2028\\u2029\\uFEFF]*");

    @FunctionalInterface
    interface Events {
        void exchange(String action, String slot, long generation, CosmicSpec snapshot);

        default void checkIdle(boolean finishing) {}
    }

    private static final class Slot {
        final String id;
        long generation;
        boolean active;

        Slot(String id) { this.id = id; }
    }

    private record Borrow<T>(T storage, Slot slot, CosmicSpec snapshot) {}

    private final String participantId;
    private final Pool<T> pool;
    private final Function<T, CosmicSpec> projection;
    private final Events events;
    private final Thread owner = Thread.currentThread();
    private final IdentityHashMap<T, Slot> slots = new IdentityHashMap<>();
    private final IdentityHashMap<Lease, Borrow<T>> borrows = new IdentityHashMap<>();
    private RuntimeException fatal;
    private boolean closed;
    private boolean operating;

    ScenarioContext(String participantId, Pool<T> pool, Function<T, CosmicSpec> projection, Events events) {
        this.participantId = participantId;
        this.pool = Objects.requireNonNull(pool);
        this.projection = Objects.requireNonNull(projection);
        this.events = events;
    }

    public String participantId() { return participantId; }

    public Lease acquire(CosmicSpec spec) {
        requireLive();
        validate(spec);
        operating = true;
        try {
            return borrow(spec);
        } finally {
            operating = false;
        }
    }

    private Lease borrow(CosmicSpec spec) {
        T storage;
        try {
            storage = Objects.requireNonNull(pool.acquire(spec), "Pool returned null storage");
        } catch (RuntimeException cause) {
            throw failPool("Pool acquire failed", cause);
        }
        Slot slot = slots.get(storage);
        if (slot != null && slot.active) {
            throw failPool("Pool acquire returned active storage", null);
        }

        CosmicSpec snapshot;
        try {
            if (slot == null && slots.size() >= SLOT_LIMIT) {
                throw new IllegalStateException("Participant slot limit (500) exceeded");
            }
            if (slot != null && slot.generation == Runner.MAX_SAFE_INTEGER) {
                throw new IllegalStateException("Generation limit exceeded");
            }
            snapshot = projection.apply(storage);
            validate(snapshot);
            if (!spec.equals(snapshot)) {
                throw new IllegalStateException("Pool snapshot differs from the requested spec");
            }
        } catch (RuntimeException cause) {
            var failure = failPool("Cannot publish acquired storage", cause);
            try {
                pool.release(storage);
            } catch (RuntimeException cleanupFailure) {
                if (cleanupFailure != failure) failure.addSuppressed(cleanupFailure);
            }
            throw failure;
        }

        if (slot == null) {
            slot = new Slot(Integer.toString(slots.size() + 1));
            slots.put(storage, slot);
        }
        slot.generation++;
        slot.active = true;
        publish("acquire", slot, snapshot);
        var lease = new Lease();
        borrows.put(lease, new Borrow<>(storage, slot, snapshot));
        return lease;
    }

    public CosmicSpec snapshot(Lease lease) {
        return requireBorrow(lease).snapshot();
    }

    public void release(Lease lease) {
        var borrow = requireBorrow(lease);
        operating = true;
        try {
            pool.release(borrow.storage());
        } catch (RuntimeException cause) {
            throw failPool("Pool release failed for slot " + borrow.slot().id, cause);
        } finally {
            operating = false;
        }
        borrows.remove(lease);
        borrow.slot().active = false;
        publish("release", borrow.slot(), null);
    }

    private Borrow<T> requireBorrow(Lease lease) {
        requireLive();
        var borrow = borrows.get(lease);
        if (borrow == null) throw new UsageException("Lease is not active in this session");
        return borrow;
    }

    private void requireLive() {
        if (Thread.currentThread() != owner || closed || operating) {
            throw new UsageException("Context requires an open, synchronous scenario");
        }
        finishCheck(false);
    }

    void finish() { finishCheck(true); }

    void close() {
        closed = true;
        borrows.clear();
        slots.clear();
    }

    private void finishCheck(boolean finishing) {
        if (fatal != null) throw fatal;
        try {
            events.checkIdle(finishing);
        } catch (RuntimeException failure) {
            fatal = failure;
            throw failure;
        }
    }

    private void publish(String action, Slot slot, CosmicSpec snapshot) {
        try {
            events.exchange(action, slot.id, slot.generation, snapshot);
        } catch (RuntimeException failure) {
            fatal = failure;
            throw failure;
        }
    }

    private PoolException failPool(String message, Throwable cause) {
        var failure = new PoolException(message, cause);
        fatal = failure;
        return failure;
    }

    private static void validate(CosmicSpec spec) {
        if (spec == null) throw new UsageException("Spec is required");
        String name = spec.name();
        if (name == null || name.length() > 40 || BLANK_NAME.matcher(name).matches()
                || !StandardCharsets.UTF_8.newEncoder().canEncode(name)) {
            throw new UsageException("Name must be UTF-8 encodable, nonblank, and at most 40 UTF-16 units");
        }
        if (spec.type() == null || !TYPES.contains(spec.type())) {
            throw new UsageException("Type must be seed, star, or planet");
        }
        if (spec.color() == null || !COLOR.matcher(spec.color()).matches()) {
            throw new UsageException("Color must be #RRGGBB");
        }
        if (!Double.isFinite(spec.size()) || spec.size() < 0.3 || spec.size() > 3.5) {
            throw new UsageException("Size must be finite and between 0.3 and 3.5");
        }
    }
}
