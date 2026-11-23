# Rust 참가자 스타터

Rust Runner는 참가자 코드와 같은 프로세스에서 실행됩니다. 참가자는 실제 객체를 소유하는 `ObjectPool`과 시나리오를 구현합니다. Runner는 대여를 추적하고 [Protocol v1](../../docs/PROTOCOL.md)에 맞춰 stdio로 통신합니다.

## 환경 준비

- [Rustup](https://rustup.rs/)으로 stable Rust와 Cargo를 설치합니다. 공통 검증기와 Bridge에는 Node.js 22 이상이 필요합니다. 첫 Cargo 빌드는 잠금 파일에 기록된 의존성을 crates.io에서 내려받습니다.
- **Windows**에서 기본 MSVC Rust를 쓰려면 Visual Studio Build Tools의 **Desktop development with C++** 워크로드와 Windows SDK가 필요합니다. `link.exe` 관련 오류가 나면 해당 구성 요소를 확인하고 새 PowerShell 또는 **Developer PowerShell for VS**에서 실행하세요. GNU Rust를 선택한 환경에서는 해당 대상의 MinGW-w64 링커를 사용하세요. 별도 링커 경로는 현재 터미널에서 `CARGO_TARGET_X86_64_PC_WINDOWS_GNU_LINKER`로 지정할 수 있습니다.
- **Linux**에서는 C 링커와 개발 도구가 필요합니다. 예를 들어 Debian/Ubuntu에서 `build-essential` 패키지를 설치합니다. **macOS**에서는 `xcode-select --install`로 Command Line Tools를 설치합니다.

저장소 루트에서 다음을 확인합니다.

```sh
rustc --version
cargo --version
node --version
cargo test --locked --manifest-path framework/adapters/rust/Cargo.toml
cargo test --locked --manifest-path tests/rust/Cargo.toml
cargo build --locked --manifest-path tests/rust/Cargo.toml
```

빌드를 먼저 끝낸 뒤 공통 검증기에 실행 파일을 전달하세요. 검증기 기본 제한은 프로세스 실행 전체에 15초이며 실행당 최대 2,000줄입니다.

**Windows PowerShell**

```powershell
node scripts/verify-protocol.mjs -- tests/rust/target/debug/galaxy-rust-fixture.exe
node scripts/verify-protocol.mjs -- tests/rust/target/debug/galaxy-rust-fixture.exe --reset-on-start
```

**POSIX 셸**

```sh
node scripts/verify-protocol.mjs -- tests/rust/target/debug/galaxy-rust-fixture
node scripts/verify-protocol.mjs -- tests/rust/target/debug/galaxy-rust-fixture --reset-on-start
```

데모는 슬롯 1을 확보하고 반환한 뒤, 같은 슬롯을 다른 이름·종류·색상·크기로 다시 확보합니다. 기본 실행에서는 3개 이벤트와 재사용 1회를 기대합니다. 시작 시 초기화를 켜면 `reset`이 앞에 추가됩니다.

## TODO 구현

1. [src/main.rs](src/main.rs)에 `CosmicObject`의 필드와 풀의 저장 구조를 정의하세요. 풀은 저장 공간을 처음 만들 때 `StorageToken::new()`로 토큰을 할당하고 그 공간과 함께 보관합니다. 재대여 시 같은 토큰을 복제하고 매번 새로운 대여 핸들을 발급하세요. 핸들은 저장 위치, 그 위치의 소유권과 현재 대여를 판별할 수 있어야 합니다.
2. `Pool::acquire`에서 용량 정책에 맞춰 공간을 선택하고 네 필드를 모두 초기화하세요. `Pool::snapshot`은 핸들을 확인하고 저장된 실제 값을 복사합니다. `Pool::release`는 핸들을 값으로 받아 유효성을 확인한 뒤 공간을 다음 확보에 쓸 수 있도록 반환합니다. 도메인 오류를 반환할 때는 기존 풀 상태를 유지하세요.
3. `scenario`에서는 `context.acquire(spec)?`, `context.snapshot(&lease)?`, `context.release(&lease)?`를 사용하세요. 반환한 대여는 같은 공간을 다시 확보해도 만료 상태입니다. 미리 읽은 스냅샷 값은 이전 상태를 보존합니다. Runner는 활성 슬롯의 토큰을 중복 확보하거나 요청과 다른 스냅샷을 읽으면 실행을 중단합니다. 진단에는 `eprintln!`을 사용하세요.
4. 참가자 풀을 직접 호출하는 단위 테스트를 작성하세요. 한 저장 공간을 확보하고 반환한 뒤 다시 확보해 실제 저장 위치와 `same_storage`를 비교하고, 새 핸들로 읽은 네 필드를 확인하세요. 오래된 핸들, 다른 풀의 핸들, 활성 공간의 중복 대여와 용량 초과도 시험하세요. JSONL 검증기는 슬롯과 세대의 순서를 확인합니다. 실제 재사용은 이러한 네이티브 테스트로 입증합니다.

```sh
cargo build --locked --manifest-path solution/rust/Cargo.toml
cargo test --locked --manifest-path solution/rust/Cargo.toml
```

시나리오 TODO를 마친 뒤 검증합니다.

```powershell
node scripts/verify-protocol.mjs -- solution/rust/target/debug/galaxy-rust-solution.exe
```

```sh
node scripts/verify-protocol.mjs -- solution/rust/target/debug/galaxy-rust-solution
```

## 로컬 Relay 시연

[플랫폼](../../README.md#3-relay와-webgl에서-시연하기)의 로컬 Relay와 WebGL 뷰어를 시작하세요. 아래 예시는 플랫폼 저장소와 Starter가 같은 상위 폴더에 있을 때의 경로입니다. 저장소가 다른 위치에 있으면 Bridge 스크립트의 경로를 바꾸세요.

```powershell
$env:GALAXY_PARTICIPANT_ID = "rust-demo"
$env:GALAXY_TOKEN = "local-demo-token"
$env:GALAXY_WS = "ws://127.0.0.1:8787/ws"
$env:GALAXY_TEST_PRESENTATION_DELAY = "1"
node ../Galaxy-Expansion/bridge/local-bridge.mjs -- tests/rust/target/debug/galaxy-rust-fixture.exe
```

```sh
GALAXY_PARTICIPANT_ID=rust-demo GALAXY_TOKEN=local-demo-token \
  GALAXY_WS=ws://127.0.0.1:8787/ws GALAXY_TEST_PRESENTATION_DELAY=1 \
  node ../Galaxy-Expansion/bridge/local-bridge.mjs -- tests/rust/target/debug/galaxy-rust-fixture
```

데모의 대기 시간은 단계별 0~3초이며 기본값은 0입니다. 첫 실행에는 새 참가자 ID를 쓰세요. 같은 ID에서 기존 슬롯을 지우고 시작하려면 실행 파일 인수로 `--reset-on-start`를 전달하세요. Bridge 로그에서 프로그램 종료 코드 `0`과 뷰어에 다시 표시되는 별을 확인하세요. 원격 토큰은 Bridge 실행 환경에서 관리하세요.

Runner는 이벤트 사이에 최소 25ms를 두며 시작은 5초, 각 응답은 출력 후 2초까지 기다립니다. 한 세션에서 관찰하는 저장 공간은 최대 500개입니다. 도메인 오류나 응답 실패가 발생하면 기존 Relay 상태가 남을 수 있습니다. 재연결 없이 종료하며, 같은 ID로 재시작할 때는 이전 상태를 지울지 먼저 결정하세요. 일반 시나리오는 유한해야 하고 실행 시간은 호스트 검증기가 제한합니다. 인터럽트 종료 상태는 운영체제에 따릅니다.
