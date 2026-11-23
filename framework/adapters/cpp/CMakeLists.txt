cmake_minimum_required(VERSION 3.24)
project(GalaxyRunnerCpp LANGUAGES CXX)

include(FetchContent)
FetchContent_Declare(nlohmann_json
    URL https://github.com/nlohmann/json/releases/download/v3.12.0/json.tar.xz
    URL_HASH SHA256=42f6e95cad6ec532fd372391373363b62a14af6d771056dbfc86160e6dfff7aa
    DOWNLOAD_EXTRACT_TIMESTAMP FALSE)
FetchContent_MakeAvailable(nlohmann_json)
find_package(Threads REQUIRED)

add_library(galaxy_runner runner.cpp session.cpp)
target_compile_features(galaxy_runner PUBLIC cxx_std_20)
target_include_directories(galaxy_runner PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}")
target_link_libraries(galaxy_runner PRIVATE nlohmann_json::nlohmann_json Threads::Threads)

get_filename_component(starter_root "${CMAKE_CURRENT_SOURCE_DIR}/../../.." ABSOLUTE)

add_executable(galaxy-cpp "${starter_root}/solution/cpp/main.cpp")
target_link_libraries(galaxy-cpp PRIVATE galaxy_runner)

include(CTest)
if(BUILD_TESTING)
    find_program(NODE_EXECUTABLE NAMES node REQUIRED)
    add_executable(galaxy-cpp-demo "${starter_root}/tests/cpp/demo.cpp")
    target_link_libraries(galaxy-cpp-demo PRIVATE galaxy_runner)

    add_executable(galaxy-cpp-tests "${starter_root}/tests/cpp/session_tests.cpp")
    target_link_libraries(galaxy-cpp-tests PRIVATE galaxy_runner nlohmann_json::nlohmann_json)

    add_test(NAME cpp_session COMMAND galaxy-cpp-tests)
    add_test(NAME cpp_transport COMMAND "${NODE_EXECUTABLE}"
        "${starter_root}/tests/cpp/transport.test.mjs" "$<TARGET_FILE:galaxy-cpp-demo>")
    set_tests_properties(cpp_session cpp_transport PROPERTIES TIMEOUT 25)
endif()
