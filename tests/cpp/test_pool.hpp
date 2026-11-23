#pragma once

#include "runner.hpp"

#include <vector>

namespace galaxy::testing {

class TestObject final : public Storage {
public:
    CosmicSpec snapshot() const override {
        if (fail_snapshot) {
            throw std::logic_error("snapshot failed");
        }
        return value;
    }

    CosmicSpec value{};
    bool borrowed = false;
    bool fail_snapshot = false;
};

// Test-only pool with stable storage and lowest-index reuse.
class TestPool final : public Pool {
public:
    explicit TestPool(std::size_t capacity = 1) {
        for (std::size_t i = 0; i < capacity; ++i) {
            objects.push_back(std::make_shared<TestObject>());
        }
    }

    std::shared_ptr<const Storage> acquire(const CosmicSpec& spec) override {
        calls.push_back("acquire");
        if (fail_acquire) {
            throw std::logic_error("acquire failed");
        }
        if (return_null) {
            return {};
        }
        if (alias_active) {
            return objects.front();
        }
        for (auto& object : objects) {
            if (!object->borrowed) {
                object->value = spec;
                object->fail_snapshot = fail_snapshot;
                if (bad_projection) {
                    object->value.color = "invalid";
                }
                if (stale_projection) {
                    object->value.name = "Wrong name";
                }
                object->borrowed = true;
                last_acquired = object.get();
                return object;
            }
        }
        throw std::logic_error("pool exhausted");
    }

    void release(const Storage& storage) override {
        calls.push_back("release");
        if (fail_release) {
            throw std::logic_error("release failed");
        }
        for (auto& object : objects) {
            if (object.get() == &storage && object->borrowed) {
                object->borrowed = false;
                return;
            }
        }
        throw std::logic_error("foreign or inactive storage");
    }

    const Storage* last_acquired = nullptr;
    std::vector<std::string> calls;
    bool alias_active = false;
    bool return_null = false;
    bool fail_acquire = false;
    bool fail_release = false;
    bool fail_snapshot = false;
    bool bad_projection = false;
    bool stale_projection = false;

private:
    std::vector<std::shared_ptr<TestObject>> objects;
};

} // namespace galaxy::testing
