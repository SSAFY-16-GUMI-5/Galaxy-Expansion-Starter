#include "runner.hpp"

namespace {

class CosmicObject final : public galaxy::Storage {
public:
    galaxy::CosmicSpec snapshot() const override {
        return fields_;
    }

    // TODO: Add a method that reinitializes all fields for a new borrow.
private:
    galaxy::CosmicSpec fields_{};
};

class ObjectPool final : public galaxy::Pool {
public:
    std::shared_ptr<const galaxy::Storage> acquire(const galaxy::CosmicSpec&) override {
        // TODO: Choose an available CosmicObject, reinitialize it, and borrow it.
        // Keep its address stable for the lifetime of this pool.
        throw std::logic_error("TODO: implement ObjectPool::acquire");
    }

    void release(const galaxy::Storage&) override {
        // TODO: Confirm that this exact object is owned and currently borrowed,
        // then mark it available. Reject invalid releases without changing state.
        throw std::logic_error("TODO: implement ObjectPool::release");
    }
};

void scenario(galaxy::Context& context) {
    const auto first = context.acquire({"Aurora", "star", "#5dcaff", 1.2});
    // TODO: Inspect the captured value with context.snapshot(first).
    context.release(first);
    // TODO: Acquire again with different values. Ensure the pool reuses storage.
}

} // namespace

int main(int argc, char** argv) {
    ObjectPool pool;
    return galaxy::run_cli(argc, argv, pool, scenario);
}
