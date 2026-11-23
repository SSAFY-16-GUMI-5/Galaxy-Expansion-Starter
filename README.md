# Galaxy Expansion Starter

> SSAFY 16기 구미 5반 · PROJECT 01 · Object Pooling

Python, C++, Java, C#, Rust 중 하나를 골라 객체를 확보하고 반환한 뒤 같은 인스턴스나 저장 공간을 재사용합니다. 참가자는 `solution/`의 객체 풀과 시나리오를 완성합니다. Runner가 확보·반환을 추적하며, 기존 Bridge와 Relay를 통해 결과가 WebGL 화면에 표시됩니다.

- [과제 명세](docs/ASSIGNMENT.md) · [Python 구현 안내](solution/README.md) · [AI 개발 절차](docs/AI_WORKFLOW.md)
- [프로토콜 v1](docs/PROTOCOL.md) · [언어 가이드](docs/LANGUAGE_GUIDE.md)
- [공동 WebGL 화면](https://ssafy-16-gumi-5.github.io/Galaxy-Expansion/) · [플랫폼 저장소](https://github.com/SSAFY-16-GUMI-5/Galaxy-Expansion)

## 1. 시작하기

1. GitHub에서 **Use this template → Create a new repository**를 선택해 자신의 저장소를 만든 후 Clone합니다.
2. [언어 가이드](docs/LANGUAGE_GUIDE.md)에서 스타터를 고르고 해당 도구와 Node.js 22 이상을 설치합니다.
3. 언어별 안내에 따라 데모와 테스트를 먼저 실행한 뒤 `solution/`의 풀링과 시나리오 TODO를 구현합니다.

## 2. 공통 검증과 Python 데모

아래는 Python 3.12 기준입니다. 다른 언어의 빌드, 테스트, 검증 명령은 [언어 가이드](docs/LANGUAGE_GUIDE.md)에 있습니다.

아래 명령은 Starter 루트에서 실행합니다.

```sh
npm test
npm run verify:fixture
node scripts/verify-protocol.mjs -- python -m framework.adapters.python --module tests.fixtures.python_runner_demo
```

첫 두 명령은 공통 검증기 자체와 JSONL 예제 파일을 검사합니다. 세 번째 명령은 동봉된 데모로 Runner가 실제 실행 과정에서 프로토콜을 지키는지 확인합니다. 데모는 참가자 TODO를 완성하기 전에도 실행할 수 있습니다.

Windows PowerShell에서 실행 정책 때문에 `npm.ps1`이 차단되면 `npm.cmd test`처럼 `npm` 대신 `npm.cmd`를 사용하세요. 플랫폼 명령에도 같은 방법을 적용할 수 있습니다.

참가자 코드의 풀과 시나리오를 완성하면 다음 명령으로 검증합니다. 어댑터에서 `--module`을 생략하면 `solution.main`을 읽습니다.

```sh
node scripts/verify-protocol.mjs -- python -m framework.adapters.python --module solution.main
```

검증기는 `init`을 보낸 뒤 이벤트마다 `ack`를 반환하고, 같은 슬롯이 반환 후 다음 세대로 재사용되는 시퀀스를 확인합니다. 실제 Python 객체의 동일성과 필드 재초기화는 참가자 단위 테스트에서 확인합니다. 테스트 방법은 [Python 구현 안내](solution/README.md)를 참고하세요.

## 3. Relay와 WebGL에서 시연하기

[Galaxy-Expansion](https://github.com/SSAFY-16-GUMI-5/Galaxy-Expansion)을 별도로 Clone합니다. 아래 예시는 Starter와 플랫폼을 같은 상위 폴더에 둔 경우입니다.

Bridge 뒤에 전달할 C++·Java·C#·Rust 실행 명령은 [언어 가이드](docs/LANGUAGE_GUIDE.md)의 각 스타터에 있습니다.

1. **터미널 A**에서 플랫폼 루트로 이동해 처음 한 번 `npm install`을 실행하고 `npm run relay`를 시작합니다.
2. **터미널 B**에서 플랫폼 루트로 이동해 `npm run dev`를 시작합니다.
3. 브라우저에서 `http://localhost:4173`을 열고 `ws://127.0.0.1:8787/ws`로 **CONNECT**합니다.
4. **터미널 C**는 **Starter 루트**에서 엽니다. Bridge는 플랫폼의 스크립트 경로로 실행합니다. 두 저장소 위치가 다르면 해당 스크립트의 절대 경로를 전달하세요. Bridge가 Starter를 작업 디렉터리로 상속한 Python을 시작하므로 Runner와 참가자 모듈을 가져올 수 있습니다.

**Windows PowerShell**

```powershell
$env:GALAXY_PARTICIPANT_ID = "my_unique_id"
$env:GALAXY_TOKEN = "local-demo-token"
$env:GALAXY_WS = "ws://127.0.0.1:8787/ws"
$env:GALAXY_TEST_PRESENTATION_DELAY = "1"
node ../Galaxy-Expansion/bridge/local-bridge.mjs -- python -m framework.adapters.python --module tests.fixtures.python_runner_demo
```

**POSIX 셸**

```sh
GALAXY_PARTICIPANT_ID=my_unique_id GALAXY_TOKEN=local-demo-token \
  GALAXY_WS=ws://127.0.0.1:8787/ws GALAXY_TEST_PRESENTATION_DELAY=1 \
  node ../Galaxy-Expansion/bridge/local-bridge.mjs -- python -m framework.adapters.python --module tests.fixtures.python_runner_demo
```

`GALAXY_TEST_PRESENTATION_DELAY`는 데모의 변화를 화면에서 보기 위한 선택 설정이며 단위는 초입니다. 데모에서는 활성 객체 수가 1 → 10 → 9 → 10으로 바뀝니다. 마지막 단계에서 반환했던 슬롯이 새 이름과 색상으로 다시 표시됩니다. 참가자 구현을 완성한 뒤에는 명령의 모듈 이름을 `solution.main`으로 바꿔 실행합니다. Bridge의 `[bridge] program exited: 0` 로그와 WebGL 화면에서 시연 결과를 확인하세요.

처음 실행할 때는 새 참가자 ID를 사용하세요. Relay는 연결이 끊겨도 참가자의 슬롯 상태를 유지합니다. 같은 ID로 다시 실행할 때 이전 상태를 지워도 된다면 Python 어댑터 인수 끝에 `--reset-on-start`를 추가하세요. 참가자 상태를 지운 뒤 슬롯과 세대가 새로 시작합니다. 이전 상태를 유지하려면 새 참가자 ID로 실행하세요.

`local-demo-token`은 로컬 Relay용입니다. 공개 HTTPS 화면을 외부 Relay에 연결하려면 TLS가 적용된 `wss://` 엔드포인트가 필요합니다. 원격 토큰은 Git이나 브라우저 코드에 넣지 마세요.

## 4. 제출 및 발표

- `solution/` 코드와 실행 방법
- 풀 자료구조와 생명주기 설계, 실제 객체 재사용과 재초기화를 입증한 테스트
- 참가자 시나리오의 공통 검증 결과와 가능하면 WebGL 시연

> 저장소 운영자는 GitHub의 **Settings → General → Template repository**에서 이 저장소를 템플릿으로 설정할 수 있습니다.
