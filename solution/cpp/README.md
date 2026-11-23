# C++ Galaxy Runner

C++20 참가자 코드를 Runner와 같은 프로세스에서 실행합니다. Runner는 실제 저장소 주소를 관찰해 슬롯 ID와 세대를 계산하고, [Protocol v1](../../docs/PROTOCOL.md)의 UTF-8 JSONL을 처리합니다. 먼저 테스트용 데모로 환경을 확인한 뒤 [main.cpp](main.cpp)의 TODO를 완성하세요.

## 준비

- Windows에서는 Visual Studio Build Tools의 **Desktop development with C++** 워크로드(MSVC와 Windows SDK), CMake 3.24 이상, Node.js 22 이상을 준비하세요. 아래 Windows 예시는 Visual Studio 2022 Developer PowerShell에서 실행합니다.
- Linux에서는 C++20을 지원하는 GCC 또는 Clang과 표준 라이브러리, CMake 3.24 이상, Node.js 22 이상을 준비하세요. macOS에서는 Xcode Command Line Tools의 Clang을 사용할 수 있습니다.
- CMake는 첫 구성 시 GitHub에서 nlohmann/json v3.12.0을 내려받고 SHA-256으로 확인합니다. 오프라인에서는 같은 릴리스 아카이브를 미리 풀어 해당 소스 디렉터리를 `-DFETCHCONTENT_SOURCE_DIR_NLOHMANN_JSON=/path/to/json`으로 지정할 수 있습니다.

## 빌드 및 데모 검증

Starter 저장소 루트에서 실행합니다.

**Windows PowerShell (Visual Studio 2022 생성기)**

```powershell
cmake -S framework/adapters/cpp -B build/cpp -G "Visual Studio 17 2022" -A x64
cmake --build build/cpp --config Release --parallel
ctest --test-dir build/cpp -C Release --output-on-failure
node scripts/verify-protocol.mjs -- ./build/cpp/Release/galaxy-cpp-demo.exe
node scripts/verify-protocol.mjs -- ./build/cpp/Release/galaxy-cpp-demo.exe --reset-on-start
```

**Linux / macOS**

```sh
cmake -S framework/adapters/cpp -B build/cpp -DCMAKE_BUILD_TYPE=Release
cmake --build build/cpp --parallel
ctest --test-dir build/cpp --output-on-failure
node scripts/verify-protocol.mjs -- ./build/cpp/galaxy-cpp-demo
node scripts/verify-protocol.mjs -- ./build/cpp/galaxy-cpp-demo --reset-on-start
```

다른 컴파일러로 검증하려면 별도 빌드 디렉터리를 사용하세요. 예를 들어 Linux에서는 `cmake -S framework/adapters/cpp -B build/cpp-clang -DCMAKE_CXX_COMPILER=clang++ -DCMAKE_BUILD_TYPE=Release`로 구성합니다. Windows에서 Ninja를 선택하면 실행 파일은 `Release/` 하위 디렉터리 없이 빌드 디렉터리에 생성됩니다.

데모는 **확보 → 반환 → 같은 저장소 재확보**를 실행하고 마지막 객체를 활성 상태로 남깁니다. 검증 결과는 기본 실행에서 이벤트 3개, 재사용 1개, 활성 객체 1개입니다. 시작 시 초기화를 사용하면 이벤트가 1개 추가됩니다. CTest의 네이티브 테스트는 실제 C++ 주소와 재초기화된 값을 비교합니다. JSONL 검증기는 외부에서 관찰 가능한 이벤트를 검사합니다.

## TODO 완성

1. `CosmicObject`에 대여할 때마다 네 필드를 초기화하는 메서드를 작성합니다.
2. `ObjectPool`이 저장소와 대여 상태를 관리하게 합니다. 예를 들어 `std::vector<std::shared_ptr<CosmicObject>>`에서 벡터가 커져도 각 객체 주소는 안정적입니다. 반환된 객체를 보관했다가 재사용하고, 잘못된 반환이나 용량 초과를 어떻게 처리할지 정하세요.
3. 풀의 `acquire`는 실제 저장소의 `shared_ptr<const Storage>`를 전달합니다. Runner는 세션 동안 주소가 재활용되지 않도록 관찰한 객체의 수명을 유지합니다. 객체에서 풀이나 Runner로 강한 소유 참조를 저장하면 순환 소유가 생길 수 있습니다.
4. 시나리오에서는 `context.acquire(spec)`, `context.snapshot(lease)`, `context.release(lease)`를 사용합니다. 대여 토큰을 복사해도 같은 대여입니다. 반환하면 모든 토큰 복사본이 만료되고, 같은 저장소를 다시 확보하면 새 토큰이 발급됩니다. 이전에 읽은 값 스냅숏은 그대로 사용할 수 있습니다.
5. 새로 빌드한 뒤 데모 명령의 실행 파일을 `galaxy-cpp`로 바꿔 검증합니다. Windows에서는 `node scripts/verify-protocol.mjs -- ./build/cpp/Release/galaxy-cpp.exe`, Linux 또는 macOS에서는 `node scripts/verify-protocol.mjs -- ./build/cpp/galaxy-cpp`를 실행하세요. 스타터 상태에서는 Acquire TODO에서 의도적으로 종료 코드 1이 발생합니다.

풀 자체 테스트로 확보 → 반환 → 재확보에서 주소가 같고 모든 필드가 새 값인지 확인하세요. 잘못된 객체 반환, 중복 반환, 용량 초과도 테스트하세요. 풀 메서드가 예외를 던지면 기존 대여 상태를 유지해야 합니다.

## Relay와 연결

[Starter의 Relay 및 뷰어 설정](../../README.md#3-relay와-webgl에서-시연하기)대로 플랫폼을 준비하고, 플랫폼 Bridge 명령의 `--` 뒤에 C++ 데모 경로를 넣습니다. 다음은 두 저장소를 나란히 둔 경우 Starter 루트에서 실행하는 Windows 예시입니다. 다른 위치에 클론했다면 Bridge 스크립트 경로를 바꾸세요.

```powershell
$env:GALAXY_PARTICIPANT_ID = "my_cpp_demo"
$env:GALAXY_TOKEN = "local-demo-token"
$env:GALAXY_WS = "ws://127.0.0.1:8787/ws"
node ../Galaxy-Expansion/bridge/local-bridge.mjs -- ./build/cpp/Release/galaxy-cpp-demo.exe
```

Linux 또는 macOS에서는 같은 환경 변수를 export하고 `node ../Galaxy-Expansion/bridge/local-bridge.mjs -- ./build/cpp/galaxy-cpp-demo`를 실행합니다. 참가자 시나리오가 완성되면 실행 파일에서 `-demo`를 빼세요. 같은 참가자 ID의 기존 상태를 의도적으로 지울 때는 실행 파일 뒤에 `--reset-on-start`를 추가합니다.

stdout은 Runner의 JSONL 전용입니다. 참가자 로그는 `std::cerr`로 기록하세요. Runner는 시나리오 하나를 한 스레드에서 실행하며, 25 ms 이상의 간격으로 이벤트를 보내고 매번 ACK를 기다립니다. 기본 제한 시간은 init 5초, ACK 2초이며, Node 검증기의 기본 전체 실행 제한 시간은 15초입니다. 새로 관찰한 저장소는 세션당 500개까지 허용합니다. 잘못된 응답이나 전송 실패 후에는 새 이벤트를 보내지 않습니다. 기존 Relay 상태를 보존하려면 새 참가자 ID로 다시 실행하세요. 원격 토큰은 Git이나 뷰어 코드에 저장하지 마세요.
