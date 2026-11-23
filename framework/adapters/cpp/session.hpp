#pragma once

#include "runner.hpp"

#include <cstdint>
#include <exception>
#include <vector>

#include <nlohmann/json_fwd.hpp>

namespace galaxy::detail {

inline constexpr std::int64_t max_safe_integer = 9'007'199'254'740'991;

class Session final : public Context {
public:
    using Exchange = std::function<void(const nlohmann::json&)>;
    using CheckInput = std::function<void(bool sending)>;

    Session(Pool& pool, std::string participant_id, Exchange exchange,
            CheckInput check_input = [](bool) {});
    Session(const Session&) = delete;
    Session& operator=(const Session&) = delete;

    const std::string& participant_id() const override;
    Lease acquire(const CosmicSpec& spec) override;
    CosmicSpec snapshot(const Lease& lease) const override;
    void release(const Lease& lease) override;
    void check_health() const;

private:
    struct Slot {
        std::shared_ptr<const Storage> storage;
        std::int64_t generation = 0;
        std::shared_ptr<const Lease::Issuance> active;
        CosmicSpec value{};
    };

    const Slot& require_active(const Lease& lease) const;
    void check_input(bool sending) const;

    Pool& pool_;
    std::string participant_id_;
    Exchange exchange_;
    CheckInput check_input_;
    std::vector<Slot> slots_;
    mutable std::exception_ptr failure_;
};

} // namespace galaxy::detail
