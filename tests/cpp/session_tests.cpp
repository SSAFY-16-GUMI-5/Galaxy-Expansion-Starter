#include "session.hpp"
#include "test_pool.hpp"

#include <iostream>
#include <limits>
#include <utility>
#include <vector>

#include <nlohmann/json.hpp>

namespace {

using namespace galaxy;
using galaxy::detail::Session;
using galaxy::testing::TestPool;
using nlohmann::json;

const CosmicSpec first{"Aurora", "star", "#5dcaff", 1.2};
const CosmicSpec second{"Reborn", "planet", "#a78bfa", 1.6};

void require(bool ok, const char* detail) {
    if (!ok) {
        throw std::runtime_error(detail);
    }
}

template <typename Error, typename Action>
void raises(Action action) {
    try {
        action();
    } catch (const Error&) {
        return;
    }
    throw std::runtime_error("expected exception was not raised");
}

struct Harness {
    explicit Harness(std::size_t capacity = 1)
        : pool(capacity), session(pool, "native-test", [&](const json& event) {
              order.push_back(pool.calls.back());
              events.push_back(event);
          }) {}

    TestPool pool;
    std::vector<std::string> order;
    std::vector<json> events;
    Session session;
};

void direct_pool_lifecycle() {
    TestPool pool;
    TestPool foreign_pool;
    const auto stored = pool.acquire(first);
    const auto foreign = foreign_pool.acquire(first);
    raises<std::logic_error>([&] { pool.release(*foreign); });
    raises<std::logic_error>([&] { pool.acquire(second); });
    pool.release(*stored);
    raises<std::logic_error>([&] { pool.release(*stored); });
    const auto reused = pool.acquire(second);
    require(stored.get() == reused.get(), "native address must be reused");
    require(reused->snapshot() == second, "all four fields must be reinitialized");
}

void reuse_and_lease_scope() {
    Harness harness;
    auto& session = harness.session;
    require(session.participant_id() == "native-test", "participant ID");

    Harness foreign;
    const auto foreign_lease = foreign.session.acquire(first);
    const auto old = session.acquire(first);
    const auto old_address = harness.pool.last_acquired;
    const auto history = session.snapshot(old);
    session.release(old);
    raises<RunnerUsageError>([&] { session.release(old); });

    const auto current = session.acquire(second);
    require(harness.pool.last_acquired == old_address, "tracked native address");
    require(history == first && session.snapshot(current) == second, "snapshot by value");
    raises<RunnerUsageError>([&] { session.snapshot(old); });
    raises<RunnerUsageError>([&] { session.release(old); });
    raises<RunnerUsageError>([&] { session.release(foreign_lease); });
    const auto copy = current;
    session.release(copy);
    raises<RunnerUsageError>([&] { session.snapshot(current); });

    const std::vector<std::string> expected{"acquire", "release", "acquire", "release"};
    require(harness.order == expected && harness.pool.calls == expected, "domain operations precede events");
    for (const auto& event : harness.events) {
        require(event.at("poolSlotId") == "1", "reuse keeps wire slot");
    }
    require(harness.events[0].at("generation") == 1 && harness.events[1].at("generation") == 1 &&
            harness.events[2].at("generation") == 2 && harness.events[3].at("generation") == 2,
            "reuse increments generation");
    require(harness.events[2].at("data") == json{{"name", second.name}, {"type", second.type},
            {"color", second.color}, {"size", second.size}}, "event carries captured fields");
}

void equal_values_are_distinct() {
    Harness harness(2);
    harness.session.acquire(first);
    const auto address = harness.pool.last_acquired;
    harness.session.acquire(first);
    require(address != harness.pool.last_acquired, "equal-valued storage must be distinct");
    require(harness.events[0].at("poolSlotId") != harness.events[1].at("poolSlotId"), "distinct slots");
    require(harness.events[1].at("generation") == 1, "new storage starts at generation 1");
}

void invalid_requests_are_recoverable() {
    Harness harness;
    std::string emoji;
    for (int i = 0; i < 20; ++i) {
        emoji += "\xf0\x9f\x8c\x9f";
    }
    for (const auto& name : {std::string{}, std::string("\xef\xbb\xbf\xe3\x80\x80"),
                            std::string("\xc0\xaf"), std::string(41, 'a'), emoji + "x"}) {
        auto spec = first;
        spec.name = name;
        raises<RunnerUsageError>([&] { harness.session.acquire(spec); });
    }
    raises<RunnerUsageError>([&] { harness.session.acquire({"x", "star", "#badhex", 1}); });
    raises<RunnerUsageError>([&] { harness.session.acquire({"x", "moon", "#5dcaff", 1}); });
    raises<RunnerUsageError>([&] {
        harness.session.acquire({"x", "star", "#5dcaff", std::numeric_limits<double>::infinity()});
    });
    require(harness.events.empty() && harness.pool.calls.empty(), "invalid input has no side effects");
    harness.session.acquire({emoji, "seed", "#ABC123", 0.3});
    require(harness.events.size() == 1, "40 UTF-16 units accepted");
}

void pool_failures_stop_the_session() {
    for (bool TestPool::*flag : {&TestPool::bad_projection, &TestPool::stale_projection,
                                 &TestPool::fail_snapshot, &TestPool::return_null, &TestPool::fail_acquire}) {
        Harness harness;
        harness.pool.*flag = true;
        raises<PoolOperationError>([&] { harness.session.acquire(first); });
        raises<PoolOperationError>([&] { harness.session.acquire(second); });
        require(harness.events.empty(), "no event for a failed borrow");
        const bool borrowed = flag != &TestPool::return_null && flag != &TestPool::fail_acquire;
        require(harness.pool.calls == (borrowed ? std::vector<std::string>{"acquire", "release"}
                                               : std::vector<std::string>{"acquire"}),
                "only a newly borrowed object can be returned");
    }

    Harness alias;
    alias.session.acquire(first);
    alias.pool.alias_active = true;
    raises<PoolOperationError>([&] { alias.session.acquire(second); });
    require(alias.events.size() == 1 && alias.pool.calls == std::vector<std::string>{"acquire", "acquire"},
            "active alias must never be returned by recovery");

    Harness release;
    const auto lease = release.session.acquire(first);
    release.pool.fail_release = true;
    raises<PoolOperationError>([&] { release.session.release(lease); });
    raises<PoolOperationError>([&] { release.session.release(lease); });
    require(release.events.size() == 1 && release.pool.calls == std::vector<std::string>{"acquire", "release"},
            "throwing release emits nothing and is not retried");
}

void slot_limit_and_transport_poisoning() {
    Harness full(501);
    for (int i = 0; i < 500; ++i) {
        full.session.acquire(first);
    }
    raises<PoolOperationError>([&] { full.session.acquire(first); });
    require(full.events.size() == 500 && full.pool.calls.back() == "release", "slot limit before publication");

    TestPool pool;
    Session session(pool, "transport-test", [](const json&) {
        throw RunnerTransportError("test transport refused event");
    });
    raises<RunnerTransportError>([&] { session.acquire(first); });
    raises<RunnerTransportError>([&] { session.acquire(second); });
    raises<RunnerTransportError>([&] { session.check_health(); });
    require(pool.calls == std::vector<std::string>{"acquire"}, "uncertain acquire has no rollback");
}

} // namespace

int main() {
    try {
        direct_pool_lifecycle();
        reuse_and_lease_scope();
        equal_values_are_distinct();
        invalid_requests_are_recoverable();
        pool_failures_stop_the_session();
        slot_limit_and_transport_poisoning();
        std::cout << "PASS: six C++ identity and lifecycle tests\n";
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
