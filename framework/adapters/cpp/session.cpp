#include "session.hpp"

#include <algorithm>
#include <cmath>
#include <utility>

#include <nlohmann/json.hpp>

namespace galaxy::detail {
namespace {

constexpr std::size_t max_slots = 500;

bool trim_space(char32_t codepoint) {
    return (codepoint >= 0x09 && codepoint <= 0x0d) ||
           (codepoint >= 0x2000 && codepoint <= 0x200a) ||
           codepoint == 0x20 || codepoint == 0xa0 || codepoint == 0x1680 ||
           codepoint == 0x2028 || codepoint == 0x2029 || codepoint == 0x202f ||
           codepoint == 0x205f || codepoint == 0x3000 || codepoint == 0xfeff;
}

bool valid_name(const std::string& name) {
    if (name.empty() || name.size() > 120) {
        return false;
    }
    try {
        // The JSON library checks UTF-8 strictly, including overlong encodings
        // and surrogate code points. Count UTF-16 units in the validated text.
        (void)nlohmann::json(name).dump();
    } catch (const nlohmann::json::type_error&) {
        return false;
    }

    int units = 0;
    bool visible = false;
    for (std::size_t i = 0; i < name.size();) {
        const auto lead = static_cast<unsigned char>(name[i++]);
        char32_t cp = lead;
        if (lead >= 0xc0) {
            const int trailing = lead < 0xe0 ? 1 : (lead < 0xf0 ? 2 : 3);
            cp = lead & (0x7f >> (trailing + 1));
            for (int j = 0; j < trailing; ++j) {
                cp = (cp << 6) | (static_cast<unsigned char>(name[i++]) & 0x3f);
            }
        }
        units += cp > 0xffff ? 2 : 1;
        visible = visible || !trim_space(cp);
    }
    return visible && units <= 40;
}

bool valid_spec(const CosmicSpec& spec) {
    return valid_name(spec.name) &&
           (spec.type == "seed" || spec.type == "star" || spec.type == "planet") &&
           spec.color.size() == 7 && spec.color.front() == '#' &&
           spec.color.find_first_not_of("0123456789abcdefABCDEF", 1) == std::string::npos &&
           std::isfinite(spec.size) && spec.size >= 0.3 && spec.size <= 3.5;
}

nlohmann::json event(const char* type, std::size_t index, std::int64_t generation) {
    return {{"type", type}, {"poolSlotId", std::to_string(index + 1)}, {"generation", generation}};
}

template <typename Operation>
decltype(auto) pool_operation(const char* phase, Operation operation) {
    try {
        return operation();
    } catch (const std::exception& error) {
        throw PoolOperationError(std::string(phase) + ": " + error.what());
    } catch (...) {
        throw PoolOperationError(std::string(phase) + ": unknown exception");
    }
}

} // namespace

Session::Session(Pool& pool, std::string participant_id, Exchange exchange, CheckInput check_input)
    : pool_(pool), participant_id_(std::move(participant_id)), exchange_(std::move(exchange)),
      check_input_(std::move(check_input)) {
    slots_.reserve(max_slots);
}

const std::string& Session::participant_id() const {
    return participant_id_;
}

void Session::check_health() const {
    if (failure_) {
        std::rethrow_exception(failure_);
    }
}

void Session::check_input(bool sending) const {
    try {
        check_input_(sending);
    } catch (...) {
        failure_ = std::current_exception();
        throw;
    }
}

Lease Session::acquire(const CosmicSpec& spec) {
    check_health();
    if (!valid_spec(spec)) {
        throw RunnerUsageError("acquire: invalid cosmic spec");
    }

    check_input(true);
    std::shared_ptr<const Storage> storage;
    bool can_return = false;
    try {
        storage = pool_operation("pool acquire", [&] { return pool_.acquire(spec); });
        if (!storage) {
            throw PoolOperationError("pool acquire returned null storage");
        }
        const auto found = std::ranges::find_if(slots_, [&](const Slot& slot) {
            return slot.storage.get() == storage.get();
        });
        if (found != slots_.end() && found->active) {
            throw PoolOperationError("pool acquire returned active storage");
        }
        can_return = true;
        const auto index = static_cast<std::size_t>(found - slots_.begin());
        if (found == slots_.end()) {
            if (slots_.size() == max_slots) {
                throw PoolOperationError("acquire: 500 observed slots exceeded");
            }
            slots_.push_back(Slot{storage, 0, {}, {}});
        }
        auto& slot = slots_[index];
        if (slot.generation == max_safe_integer) {
            throw PoolOperationError("acquire: maximum generation exceeded");
        }
        auto value = pool_operation("pool snapshot", [&] { return storage->snapshot(); });
        if (!valid_spec(value) || value != spec) {
            throw PoolOperationError("pool snapshot must match the requested cosmic spec");
        }

        Lease lease(index);
        auto message = event("acquire", index, slot.generation + 1);
        message["data"] = {{"name", value.name}, {"type", value.type},
                           {"color", value.color}, {"size", value.size}};
        ++slot.generation;
        slot.value = std::move(value);
        slot.active = lease.issuance_;
        can_return = false; // Once publication starts, delivery can be uncertain.
        exchange_(message);
        return lease;
    } catch (...) {
        failure_ = std::current_exception();
        if (can_return) {
            try {
                pool_.release(*storage);
            } catch (...) {
                // Preserve the original fault.
            }
        }
        throw;
    }
}

const Session::Slot& Session::require_active(const Lease& lease) const {
    check_health();
    if (lease.slot_ >= slots_.size() || slots_[lease.slot_].active != lease.issuance_) {
        throw RunnerUsageError("lease is foreign, stale, or already released");
    }
    return slots_[lease.slot_];
}

CosmicSpec Session::snapshot(const Lease& lease) const {
    const auto& slot = require_active(lease);
    check_input(false);
    return slot.value;
}

void Session::release(const Lease& lease) {
    const auto& active = require_active(lease);
    check_input(true);
    try {
        auto message = event("release", lease.slot_, active.generation);
        pool_operation("pool release", [&] { pool_.release(*active.storage); });
        slots_[lease.slot_].active.reset();
        exchange_(message);
    } catch (...) {
        failure_ = std::current_exception();
        throw;
    }
}

} // namespace galaxy::detail
