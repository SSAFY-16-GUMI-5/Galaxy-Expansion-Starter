# AI Agent Instructions — Galaxy Expansion Starter

이 파일은 이 저장소에서 코드를 생성하거나 수정하는 AI 코딩 에이전트의 작업 계약입니다.

## 코드 작성과 검증 담당

Galaxy Expansion 개발 작업을 배정할 때 코드 작성·수정, 코드 리뷰, 자동 테스트 및 통합 검증은 Claude Opus 5.5 (`claude-opus-5-5`)가 담당합니다. Orca 워커를 시작할 때 `--agent claude --model claude-opus-5-5`로 모델을 지정하십시오. 오케스트레이터는 작업 범위와 의존성, 결과 취합을 담당합니다. 지정 모델을 사용할 수 없으면 해당 작업을 보류하고 사용자에게 알리십시오.

## 목적과 우선순위

1. **학습 우선:** 참가자가 객체지향 설계와 Object Pooling을 이해하도록 돕습니다.
2. **프로토콜 준수:** `docs/PROTOCOL.md` v1을 수정하지 않고 따릅니다.
3. **실행 가능성:** 선택한 언어의 참가자 코드, 단위 테스트와 Runner를 실행하는 방법을 안내합니다.
4. **코드 품질:** 소유권·생명주기·반환 후 사용 금지·재사용 시 초기화·오류 처리를 명시합니다.

## 작업 시작 전

- `README.md`, `docs/ASSIGNMENT.md`, `docs/PROTOCOL.md`, `docs/AI_WORKFLOW.md`를 읽으십시오.
- [언어 가이드](docs/LANGUAGE_GUIDE.md)에서 참가자가 선택한 스타터와 도구를 확인하십시오.
- 참가자 코드는 `solution/`에 작성합니다. 언어별 CI가 필요하면 새 워크플로를 추가할 수 있습니다. 기존 `verify.yml`은 변경하지 마십시오.
- 기존 인터페이스와 TODO, [테스트 가이드](solution/README.md)를 활용하십시오. 참가자가 명시적으로 구현 도움을 요청하면 설명과 단계별 구현으로 지원할 수 있습니다.

## 출력 형식 및 동작

참가자 코드의 통신은 Runner가 처리합니다. 아래 항목은 Runner의 프로토콜 경계에 적용됩니다.

- stdin: `{"type":"init","participantId":"..."}` 및 `ack`/`error` 메시지를 **줄 단위**로 읽습니다.
- stdout: **한 줄에 UTF-8 JSON 객체 하나**. `acquire`, `release`, `reset` 이외의 메시지를 출력하지 않습니다.
- stderr: 사람이 읽을 로그, 오류와 디버그 출력.
- `acquire`: `poolSlotId`, `generation`, `data` (`name`, `type`, `color`, `size`)를 출력합니다.
- `release`: 같은 `poolSlotId`, 정확한 현재 `generation`을 출력합니다.
- 새로운 슬롯은 generation=1, 반환 후 재사용은 같은 슬롯의 generation+1입니다.
- 브리지/서버가 `participantId`를 부여하므로 stdout 이벤트에 임의의 참가자 ID를 싣지 않습니다.
- Runner는 이벤트마다 대응되는 `ack`를 받은 뒤 진행합니다. `error` 또는 응답 시간 초과가 발생하면 전송을 중단합니다.

## 설계 분리

- 참가자 도메인은 `CosmicObject`, `ObjectPool`, 저장 공간과 대여 수명을 관리합니다.
- 시나리오의 확보와 반환은 선택한 언어의 Runner가 제공하는 컨텍스트를 사용합니다. Python에서는 `solution.main`이 `create_pool()`, `scenario(context)`, `snapshot(obj)`를 제공합니다.
- Runner는 객체의 동일성에서 슬롯과 세대를 파생하고 JSONL 및 CLI를 처리합니다. 참가자 코드에 프로토콜 처리를 추가하지 마십시오.
- 언어별 단위 테스트는 실제 인스턴스나 저장 공간의 동일성과 재초기화를 확인합니다. 독립 검증기는 JSONL 이벤트를 검사합니다.
- 완성 전에는 언어별 데모로 Runner를 확인하십시오. 참가자 풀과 시나리오를 완성한 뒤에는 해당 프로그램을 공통 검증기로 실행하십시오.

## AI가 피해야 할 행동

- `scripts/`, `contracts/`, `docs/PROTOCOL.md`, 검증 워크플로의 규칙을 정답에 맞추려고 변경하지 않습니다.
- 실패하는 테스트를 삭제하거나 느슨하게 고쳐 통과시키지 않습니다.
- 내부에서 객체를 재사용하지 않으면서 `generation`만 올려 '구현 완료'라고 보고하지 않습니다.
- 실제 참가자의 프로그램을 서버에서 실행하는 구조로 변경하지 않습니다.
- 원격 토큰을 Git에 커밋하거나 브라우저 JS에 넣지 않습니다.
- 불필요한 프레임워크·네트워크 라이브러리·복잡한 추상화를 도입하지 않습니다.

## 생성 후 보고 형식

- 생성한 파일과 역할
- 빌드/실행/테스트 명령
- 남은 TODO와 공부할 개념
- 실행한 검증 및 실제 결과(실행하지 못했다면 그 사실을 명시)
- 보안/생명주기상 주의점
