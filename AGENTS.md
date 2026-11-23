# AI Agent Instructions — Galaxy Expansion Starter

이 파일은 이 저장소에서 코드를 생성하거나 수정하는 AI 코딩 에이전트의 작업 계약입니다.

## 목적과 우선순위

1. **학습 우선:** 참가자가 객체지향 설계와 Object Pooling을 이해하도록 돕습니다.
2. **프로토콜 준수:** `docs/PROTOCOL.md` v1을 수정하지 않고 따릅니다.
3. **실행 가능성:** 선택 언어의 실제 컴파일/실행 환경, 간단한 단위 테스트, CLI 실행 방법을 제공합니다.
4. **코드 품질:** 소유권·생명주기·반환 후 사용 금지·재사용 시 초기화·오류 처리를 명시합니다.

## 작업 시작 전

- `README.md`, `docs/ASSIGNMENT.md`, `docs/PROTOCOL.md`, `docs/AI_WORKFLOW.md`를 읽으십시오.
- 참가자 언어가 정해지지 않았다면 **언어 하나만** 확인하십시오.
- 참가자 코드는 `solution/`에 작성합니다. 언어별 CI가 필요하면 **새** `.github/workflows/solution-<lang>.yml`을 추가해도 되지만 기존 `verify.yml`은 변경하지 마십시오. 참가자가 지정한 개발 언어와 무관한 도구를 강제하지 마십시오.
- 처음에는 완성된 객체 풀 대신 *인터페이스 + TODO + 테스트 가이드*를 제공합니다. 참가자가 명시적으로 구현 도움을 요청하면 설명과 단계별 구현으로 지원할 수 있습니다.

## 출력 형식 및 동작

- stdin: `{"type":"init","participantId":"..."}` 및 `ack`/`error` 메시지를 **줄 단위**로 읽습니다.
- stdout: **한 줄에 UTF-8 JSON 객체 하나**. `acquire`, `release`, `reset` 이외의 메시지를 출력하지 않습니다.
- stderr: 사람이 읽을 로그, 오류와 디버그 출력.
- `acquire`: `poolSlotId`, `generation`, `data` (`name`, `type`, `color`, `size`)를 출력합니다.
- `release`: 같은 `poolSlotId`, 정확한 현재 `generation`을 출력합니다.
- 새로운 슬롯은 generation=1, 반환 후 재사용은 같은 슬롯의 generation+1입니다.
- 브리지/서버가 `participantId`를 부여하므로 stdout 이벤트에 임의의 참가자 ID를 싣지 않습니다.
- 즉시 전송 완료/서버 적용을 가정하지 마십시오. 필요하면 stdin으로 오는 `ack` 또는 `error`를 확인합니다.

## 설계 분리

- Domain: `CosmicObject`, `ObjectPool`, 메모리 수명 및 자료구조
- Protocol Adapter: JSONL 입력/출력, 직렬화와 역직렬화
- Application: 학습 시나리오, CLI 시작과 종료
- Tests: 언어별 단위 테스트(실제 참조/저장 공간 재사용), 독립 검증기(JSONL 형식)

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
