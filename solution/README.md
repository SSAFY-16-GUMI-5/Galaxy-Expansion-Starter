# Python 참가자 구현

`solution/`의 TODO를 완성하는 것이 과제입니다. Python Runner는 참가자 코드와 같은 프로세스에서 호출되며 JSONL 입출력, 슬롯 ID, 세대 번호, 이벤트 수신 확인을 처리합니다.

## 객체 풀과 시나리오

`solution/main.py`에서 `framework.adapters.python`의 `CosmicSpec`과 `ScenarioContext`를 사용합니다. Runner가 `solution.main`에서 호출하는 세 함수는 다음과 같습니다.

| 함수 | 역할 |
| --- | --- |
| `create_pool()` | 대여 중인 객체가 없는 새 풀을 반환합니다. 풀은 `acquire(spec)`와 `release(obj)`를 제공합니다. |
| `scenario(context)` | `context.acquire(spec)`, `context.snapshot(lease)`, `context.release(lease)`를 사용해 유한한 시나리오를 실행합니다. |
| `snapshot(obj)` | 제공된 함수가 실제 객체의 현재 `name`, `type`, `color`, `size`를 읽어 `CosmicSpec`으로 반환합니다. 모델을 바꾸면 이 함수도 맞춰 수정하세요. |

풀은 `acquire(spec)`에서 확보한 실제 `CosmicObject` 인스턴스를 반환하고, `release(obj)`에서 그 인스턴스를 회수합니다. 다시 확보할 때 재사용할 객체의 네 필드를 새 값으로 초기화하세요. 용량과 사용 가능 객체를 관리하는 자료구조는 참가자가 설계합니다.

시나리오는 한 객체를 확보한 뒤 반환하고, 다른 속성으로 같은 저장 공간을 다시 확보하는 흐름부터 작성하세요. 시나리오가 받는 `lease`는 한 번의 대여를 가리킵니다. 반환한 대여는 만료되며, 같은 인스턴스를 다시 확보하면 새 대여가 생깁니다. 활성 대여의 `context.snapshot(lease)`는 확보 시의 불변 값을 돌려줍니다. 이미 읽어 둔 값은 반환 뒤에도 당시 상태로 남습니다.

Runner는 확보가 성공한 실제 인스턴스의 동일성을 기준으로 슬롯을 정합니다. 같은 인스턴스가 반환 후 다시 확보되면 슬롯 ID는 유지되고 세대는 1에서 2로 증가합니다. 시나리오의 모든 확보와 반환을 `context`로 호출하세요. 시나리오에서 JSONL, 슬롯 ID 또는 세대 번호를 만들 필요가 없습니다. 진단 로그가 필요하면 stderr에만 출력하세요.

## 검증

Starter 루트에서 Python 단위 테스트 파일을 작성한 후 실행하세요. 예를 들어 `solution/test_pool.py`에 `unittest` 테스트를 작성했다면 다음과 같이 실행합니다.

```sh
python -m unittest discover -s solution -p "test_*.py"
```

단위 테스트는 Runner를 거치지 않고 풀을 호출합니다. 한 슬롯의 첫 인스턴스와 반환 후 같은 슬롯에서 다시 확보한 인스턴스를 `is`로 비교하고, `name`, `type`, `color`, `size`가 두 번째 요청 값으로 바뀌었는지 확인합니다. 첫 참조는 테스트의 동일성 비교에만 사용하고, 객체 속성은 현재 대여가 유효할 때 읽습니다. 중복 반환, 다른 풀의 객체 반환과 사용 중인 인스턴스의 중복 대여도 검사하세요.

풀과 시나리오 TODO를 모두 완성한 뒤 공통 검증기를 실행합니다.

```sh
node scripts/verify-protocol.mjs -- python -m framework.adapters.python --module solution.main
```

완성 전 Runner 경로를 먼저 확인하려면 `--module tests.fixtures.python_runner_demo`로 실행하세요. 공통 검증기는 이벤트의 형식과 순서, 반환 후 동일 슬롯의 세대 증가를 검사합니다. 로컬 Relay와 WebGL에서 확인하려면 [저장소 README](../README.md#3-relay와-webgl에서-시연하기)의 명령을 사용하세요.
