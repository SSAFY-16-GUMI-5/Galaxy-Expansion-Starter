#include "test_pool.hpp"

#include <string_view>

int main(int argc, char** argv) {
    galaxy::testing::TestPool pool;
    const auto scenario = [](galaxy::Context& context) {
        const auto first = context.acquire({"Orion", "star", "#5dcaff", 1.2});
        context.release(first);
        context.acquire({"\xeb\xb3\x84 \xf0\x9f\x8c\x9f", "planet", "#a78bfa", 1.6});
    };
    if (argc == 2 && std::string_view(argv[1]) == "--test-short-timeouts") {
        galaxy::Options options;
        options.init_timeout = std::chrono::milliseconds(300);
        options.ack_timeout = std::chrono::milliseconds(300);
        return galaxy::run(pool, scenario, options);
    }
    return galaxy::run_cli(argc, argv, pool, scenario);
}
