# Galaxy Expansion C# 참가자 가이드

Object Pool을 구현하고 C# Runner로 [Protocol v1](../../docs/PROTOCOL.md) 이벤트를 전송합니다. .NET 8 SDK와 Node.js 22 이상을 설치하고 Starter 저장소 루트에서 명령을 실행하세요. 아래 빌드 및 검증 명령은 Windows PowerShell과 POSIX 셸에서 동일합니다. C# 프로젝트에는 외부 NuGet 패키지가 필요하지 않습니다.

## 데모부터 실행하기

```sh
dotnet --version
node --version
dotnet build tests/csharp/Galaxy.Runner.Tests.csproj -c Release
dotnet tests/csharp/bin/Release/net8.0/Galaxy.Runner.Tests.dll --test
node scripts/verify-protocol.mjs -- dotnet tests/csharp/bin/Release/net8.0/Galaxy.Runner.Tests.dll
node scripts/verify-protocol.mjs -- dotnet tests/csharp/bin/Release/net8.0/Galaxy.Runner.Tests.dll --reset-on-start
```

첫 번째 검증은 acquire 2회, release 1회와 동일 슬롯 재사용 1회를 보고합니다. 마지막 검증에는 시작 시 reset 이벤트 1회가 추가됩니다. 네이티브 테스트는 `ReferenceEquals`로 실제 저장 인스턴스를 비교하고 모든 필드가 재초기화되는지 확인합니다. Node 검증기는 JSONL의 슬롯과 세대 전이를 확인합니다. 먼저 빌드하고 DLL을 실행하면 빌드 메시지가 JSONL에 섞이지 않고 기본 15초 검증 시간도 빌드에 쓰이지 않습니다.

## 참가자 TODO 구현하기

1. [Program.cs](Program.cs)의 `CosmicObject`에 표시 필드와 필요한 상태를 추가합니다. `Snapshot()`은 현재 필드로 불변 `CosmicSpec` 값을 만들어 반환합니다.
2. `ObjectPool`에서 사용 가능한 저장 인스턴스와 대여 중인 인스턴스를 관리합니다. 고정 또는 가변 용량을 고르고 용량 한도를 만났을 때의 동작을 정하세요. `Acquire`에서 이름, 종류, 색상, 크기와 나머지 재사용 상태를 초기화합니다. `Release`에서는 다른 풀의 객체나 이미 반환한 객체를 거부합니다. 실패한 풀 연산은 기존 상태를 유지해야 합니다.
3. `RunScenario`에서 `context.Acquire(spec)`, `context.Snapshot(lease)`, `context.Release(lease)`를 사용합니다. 반환한 저장 인스턴스를 다시 빌리는 순서를 포함하고 시나리오를 유한하게 유지하세요. 각 TODO를 완료하면서 해당 `NotImplementedException`을 구현으로 교체합니다. 완성 전에는 데모로 Runner를 검증할 수 있습니다.
4. 직접 만든 풀에 대해 `ReferenceEquals`, 재초기화, 중복 반환, 외부 참조, 용량 한도를 테스트한 뒤 참가자 시나리오를 검증합니다.

```sh
dotnet build solution/csharp/Galaxy.Solution.csproj -c Release
node scripts/verify-protocol.mjs -- dotnet solution/csharp/bin/Release/net8.0/Galaxy.Solution.dll
```

풀은 저장 인스턴스를 소유합니다. 각 `Lease`는 한 번의 대여에만 유효하므로 반환 즉시 사용을 끝내세요. 예전에 받아둔 불변 스냅샷은 계속 읽을 수 있습니다. 시나리오는 실행 스레드에서 동기적으로 Context를 사용하고, 로그는 stderr로 보냅니다. Runner는 실제 저장 참조에서 슬롯과 세대를 계산합니다. 참가자 코드는 슬롯 ID나 JSONL을 생성할 필요가 없습니다.

## 로컬 Relay와 WebGL에서 보기

Starter와 [Galaxy-Expansion](https://github.com/SSAFY-16-GUMI-5/Galaxy-Expansion)을 같은 상위 폴더에 두세요. 플랫폼에서 `npm install` 후 별도 터미널에서 `npm run relay`와 `npm run dev`를 실행합니다. 브라우저에서 `http://localhost:4173`을 열고 `ws://127.0.0.1:8787/ws`로 연결하세요. PowerShell 실행 정책이 npm을 차단하면 `npm.cmd`를 쓰세요.

**Windows PowerShell** · Starter 루트

```powershell
$env:GALAXY_PARTICIPANT_ID = "csharp_demo"
$env:GALAXY_TOKEN = "local-demo-token"
$env:GALAXY_WS = "ws://127.0.0.1:8787/ws"
node ../Galaxy-Expansion/bridge/local-bridge.mjs -- dotnet tests/csharp/bin/Release/net8.0/Galaxy.Runner.Tests.dll
```

**POSIX** · Starter 루트

```sh
GALAXY_PARTICIPANT_ID=csharp_demo GALAXY_TOKEN=local-demo-token \
  GALAXY_WS=ws://127.0.0.1:8787/ws \
  node ../Galaxy-Expansion/bridge/local-bridge.mjs -- dotnet tests/csharp/bin/Release/net8.0/Galaxy.Runner.Tests.dll
```

완성한 참가자 코드로 실행할 때는 DLL 경로를 `solution/csharp/bin/Release/net8.0/Galaxy.Solution.dll`로 바꾸세요. 처음 연결할 때는 고유 ID를 사용합니다. 같은 ID를 다시 쓰면서 기존 표시 상태를 의도적으로 지우려면 DLL 경로 뒤에 `--reset-on-start`를 붙입니다. 데모는 두 번째 대여를 활성 상태로 남기므로 뷰어에서 `새로운 행성`의 세대가 2인 상태를 확인할 수 있습니다. 원격 연결은 Bridge 환경 변수에 토큰을 설정하고 `wss://` 주소를 사용하세요. 토큰은 Git이나 브라우저 코드에 넣지 마세요.

## 실행 한도와 실패 처리

- 한 프로세스에서 새 풀과 동기 시나리오를 한 번 실행합니다. 최대 500개의 서로 다른 저장 참조를 추적하며, 줄당 UTF-8 8,000바이트와 v1의 안전한 정수 범위를 적용합니다.
- Runner는 init에 5초, 개별 이벤트 응답에 2초를 기다립니다. 이벤트는 25ms 이상 간격으로 하나씩 전송합니다. Node 검증기의 기본 15초 제한에는 시나리오와 모든 ack 대기가 포함됩니다.
- ack가 실패하면 전송을 중단하고 stderr에 오류를 남깁니다. 실패 후 로컬과 Relay 상태가 다를 수 있습니다. 마지막 ack를 확인한 뒤 시나리오가 끝나면 활성 객체는 화면에 남습니다. 필요하면 시나리오에서 명시적으로 반환하세요.
