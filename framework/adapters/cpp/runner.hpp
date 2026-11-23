#pragma once

#include <chrono>
#include <cstddef>
#include <functional>
#include <memory>
#include <stdexcept>
#include <string>

namespace galaxy {

struct CosmicSpec {
    std::string name;
    std::string type;
    std::string color;
    double size = 0;
    bool operator==(const CosmicSpec&) const = default;
};

class Storage {
public:
    virtual ~Storage() = default;
    virtual CosmicSpec snapshot() const = 0;
};

class Pool {
public:
    virtual ~Pool() = default;
    // Return the actual pool-owned object. Keep this object's address stable
    // and reuse the same Storage instance when the same slot is borrowed again.
    virtual std::shared_ptr<const Storage> acquire(const CosmicSpec& spec) = 0;
    virtual void release(const Storage& object) = 0;
};

class RunnerUsageError : public std::runtime_error {
    using std::runtime_error::runtime_error;
};
class PoolOperationError : public std::runtime_error {
    using std::runtime_error::runtime_error;
};
class RunnerTransportError : public std::runtime_error {
    using std::runtime_error::runtime_error;
};

namespace detail { class Session; }

class Lease {
public:
    Lease(const Lease&) = default;
    Lease& operator=(const Lease&) = default;

private:
    friend class detail::Session;
    struct Issuance {};
    explicit Lease(std::size_t slot)
        : slot_(slot), issuance_(std::make_shared<Issuance>()) {}

    std::size_t slot_;
    std::shared_ptr<const Issuance> issuance_;
};

class Context {
public:
    virtual ~Context() = default;
    virtual const std::string& participant_id() const = 0;
    virtual Lease acquire(const CosmicSpec& spec) = 0;
    virtual CosmicSpec snapshot(const Lease& lease) const = 0;
    virtual void release(const Lease& lease) = 0;
};

struct Options {
    bool reset_on_start = false;
    std::chrono::milliseconds init_timeout{5000};
    std::chrono::milliseconds ack_timeout{2000};
};

using Scenario = std::function<void(Context&)>;
// Run once per producer process, with a fresh pool and a synchronous scenario.
int run(Pool& pool, const Scenario& scenario, Options options = {});
int run_cli(int argc, char** argv, Pool& pool, const Scenario& scenario);

} // namespace galaxy
