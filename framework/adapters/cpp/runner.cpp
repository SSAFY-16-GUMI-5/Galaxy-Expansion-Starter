#include "session.hpp"

#include <chrono>
#include <cmath>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <optional>
#include <string_view>
#include <thread>
#include <utility>

#include <nlohmann/json.hpp>

#ifdef _WIN32
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#else
#include <cerrno>
#include <csignal>
#include <unistd.h>
#endif

namespace galaxy {
namespace {

using Clock = std::chrono::steady_clock;
using namespace std::chrono_literals;
using nlohmann::json;

constexpr std::size_t max_line_bytes = 8000;

struct ProcessPipes {
    ProcessPipes() {
#ifndef _WIN32
        if (std::signal(SIGPIPE, SIG_IGN) == SIG_ERR) {
            throw RunnerTransportError("init: could not configure broken-pipe handling");
        }
#endif
    }

    static std::size_t read(char* buffer, std::size_t size) {
#ifdef _WIN32
        DWORD count = 0;
        if (ReadFile(GetStdHandle(STD_INPUT_HANDLE), buffer, static_cast<DWORD>(size), &count, nullptr)) {
            return count;
        }
        const auto error = GetLastError();
        if (error == ERROR_BROKEN_PIPE || error == ERROR_HANDLE_EOF) {
            return 0;
        }
        throw RunnerTransportError("stdin read failed (Win32 " + std::to_string(error) + ")");
#else
        const auto count = ::read(STDIN_FILENO, buffer, size);
        if (count < 0) {
            throw RunnerTransportError("stdin read failed (errno " + std::to_string(errno) + ")");
        }
        return static_cast<std::size_t>(count);
#endif
    }

    static void write(std::string_view bytes) {
        while (!bytes.empty()) {
#ifdef _WIN32
            DWORD count = 0;
            if (!WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), bytes.data(),
                           static_cast<DWORD>(bytes.size()), &count, nullptr)) {
                throw RunnerTransportError("stdout write failed (Win32 " + std::to_string(GetLastError()) + ")");
            }
#else
            const auto count = ::write(STDOUT_FILENO, bytes.data(), bytes.size());
            if (count < 0) {
                throw RunnerTransportError("stdout write failed (errno " + std::to_string(errno) + ")");
            }
#endif
            if (count == 0) {
                throw RunnerTransportError("stdout write returned zero bytes");
            }
            bytes.remove_prefix(static_cast<std::size_t>(count));
        }
    }
};

struct Reply {
    std::string line;
    Clock::time_point received;
};

struct Input {
    std::mutex mutex;
    std::condition_variable changed;
    std::optional<Clock::time_point> awaiting_since{Clock::now()};
    std::optional<Reply> reply;
    std::string fault;
    bool eof = false;
    bool closed = false;
};

void read_lines(Input& input) {
    std::string partial;
    char bytes[4096];
    for (;;) {
        const auto count = ProcessPipes::read(bytes, sizeof(bytes));
        const auto received = Clock::now();
        std::lock_guard lock(input.mutex);
        if (input.closed) {
            return;
        }
        if (count == 0) {
            input.eof = true;
            if (!partial.empty()) {
                input.fault = "unterminated JSONL input at EOF";
            }
        }
        for (const char byte : std::string_view(bytes, count)) {
            if (!input.awaiting_since || received < *input.awaiting_since || input.reply) {
                input.fault = "unsolicited control message";
                break;
            }
            if (byte == '\n') {
                if (!partial.empty() && partial.back() == '\r') {
                    partial.pop_back();
                }
                input.reply = Reply{std::move(partial), received};
                partial.clear();
            } else {
                partial.push_back(byte);
                if (partial.size() > max_line_bytes &&
                    (partial.size() > max_line_bytes + 1 || byte != '\r')) {
                    input.fault = "JSONL input exceeds 8000 bytes";
                    break;
                }
            }
        }
        input.changed.notify_one();
        if (input.eof || !input.fault.empty()) {
            return;
        }
    }
}

bool valid_participant_id(std::string_view id) {
    return !id.empty() && id.size() <= 32 &&
           id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-") ==
               std::string_view::npos;
}

bool valid_revision(const json& revision) {
    if (!revision.is_number()) {
        return false;
    }
    const auto value = revision.get<double>();
    return value >= 1 && value <= detail::max_safe_integer && std::trunc(value) == value;
}

class Transport {
public:
    Transport() {
        // Read raw process pipes so a blocked reader holds no C runtime stream
        // lock at process exit. The reader owns its state until read unblocks.
        std::thread([state = input_] {
            try {
                read_lines(*state);
            } catch (const std::exception& error) {
                std::lock_guard lock(state->mutex);
                state->fault = error.what();
                state->changed.notify_one();
            }
        }).detach();
    }

    ~Transport() {
        std::lock_guard lock(input_->mutex);
        input_->closed = true;
    }

    std::string init(std::chrono::milliseconds timeout) {
        const auto message = read_object("init", *input_->awaiting_since + timeout);
        const auto id = message.find("participantId");
        if (message.find("type") == message.end() || message["type"] != "init" ||
            id == message.end() || !id->is_string() || !valid_participant_id(id->get_ref<const std::string&>())) {
            throw RunnerTransportError("init: expected init with a valid participantId");
        }
        return id->get<std::string>();
    }

    void check_idle(bool sending = false) const {
        std::lock_guard lock(input_->mutex);
        check_fault("idle");
        if (sending && input_->eof) {
            throw RunnerTransportError("idle: stdin reached EOF before next event");
        }
    }

    void exchange(const json& event, std::chrono::milliseconds timeout) {
        const auto action = event.at("type").get<std::string>();
        auto phase = action;
        if (event.contains("poolSlotId")) {
            phase += " slot " + event.at("poolSlotId").get<std::string>() +
                     " generation " + event.at("generation").dump();
        }
        auto line = event.dump();
        if (line.size() > max_line_bytes) {
            throw RunnerTransportError(phase + ": event exceeds 8000 bytes");
        }
        line.push_back('\n');

        std::this_thread::sleep_until(next_send_);
        Clock::time_point sent;
        {
            std::lock_guard lock(input_->mutex);
            check_fault(phase);
            if (input_->eof) {
                throw RunnerTransportError(phase + ": stdin reached EOF before writing event");
            }
            input_->awaiting_since = Clock::now();
            try {
                pipes_.write(line);
            } catch (const RunnerTransportError& error) {
                throw RunnerTransportError(phase + ": " + error.what());
            }
            sent = Clock::now();
        }
        next_send_ = sent + 25ms;

        const auto reply = read_object(phase + " ack", sent + timeout);
        const auto type = reply.find("type");
        const auto message = reply.find("message");
        if (type != reply.end() && *type == "error" && message != reply.end() && message->is_string()) {
            throw RunnerTransportError(phase + ": remote rejection: " + message->dump());
        }
        const auto reply_action = reply.find("action");
        const auto revision = reply.find("revision");
        if (type == reply.end() || *type != "ack" ||
            reply_action == reply.end() || *reply_action != action ||
            revision == reply.end() || !valid_revision(*revision)) {
            throw RunnerTransportError(phase + ": expected matching ack with a valid revision");
        }
    }

private:
    void check_fault(const std::string& phase) const {
        if (!input_->fault.empty()) {
            throw RunnerTransportError(phase + ": " + input_->fault);
        }
    }

    json read_object(const std::string& phase, Clock::time_point deadline) {
        std::string line;
        {
            std::unique_lock lock(input_->mutex);
            input_->changed.wait_until(lock, deadline, [&] {
                return input_->reply || input_->eof || !input_->fault.empty();
            });
            check_fault(phase);
            if (!input_->reply && input_->eof) {
                throw RunnerTransportError(phase + ": stdin reached EOF");
            }
            if (!input_->reply || input_->reply->received > deadline) {
                throw RunnerTransportError(phase + ": timed out");
            }
            line = std::move(input_->reply->line);
            input_->reply.reset();
            input_->awaiting_since.reset();
        }

        try {
            // nlohmann/json accepts a leading BOM. Protocol input is plain UTF-8.
            if (line.starts_with("\xef\xbb\xbf")) {
                throw RunnerTransportError(phase + ": unexpected UTF-8 BOM");
            }
            if (line.find('\0') != std::string::npos) {
                throw RunnerTransportError(phase + ": invalid UTF-8 JSON: embedded NUL");
            }
            auto message = json::parse(line);
            if (!message.is_object()) {
                throw RunnerTransportError(phase + ": expected a JSON object");
            }
            return message;
        } catch (const json::exception& error) {
            throw RunnerTransportError(phase + ": invalid UTF-8 JSON: " + error.what());
        }
    }

    ProcessPipes pipes_;
    std::shared_ptr<Input> input_ = std::make_shared<Input>();
    Clock::time_point next_send_ = Clock::now();
};

} // namespace

int run(Pool& pool, const Scenario& scenario, Options options) {
    try {
        if (options.init_timeout <= 0ms || options.ack_timeout <= 0ms) {
            throw RunnerUsageError("timeouts must be positive");
        }
        Transport transport;
        auto participant = transport.init(options.init_timeout);
        if (options.reset_on_start) {
            transport.exchange({{"type", "reset"}}, options.ack_timeout);
        }
        transport.check_idle();
        detail::Session session(pool, std::move(participant), [&](const json& event) {
            transport.exchange(event, options.ack_timeout);
        }, [&](bool sending) { transport.check_idle(sending); });
        scenario(session);
        session.check_health();
        transport.check_idle();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << "[galaxy-cpp] " << error.what() << '\n';
    } catch (...) {
        std::cerr << "[galaxy-cpp] unknown exception\n";
    }
    return 1;
}

int run_cli(int argc, char** argv, Pool& pool, const Scenario& scenario) {
    Options options;
    if (argc == 2 && std::string_view(argv[1]) == "--reset-on-start") {
        options.reset_on_start = true;
    } else if (argc != 1) {
        std::cerr << "Usage: " << argv[0] << " [--reset-on-start]\n";
        return 2;
    }
    return run(pool, scenario, options);
}

} // namespace galaxy
