# 언어 가이드

현재 제공하는 참가자 스타터와 Runner는 **Python용**입니다. Python 3으로 참가자 코드와 테스트를 실행하고, Node.js 22 이상으로 공통 검증기와 로컬 플랫폼을 실행합니다. Runner는 Python 표준 라이브러리를 사용합니다.

## Python에서 시작하기

1. [Python 구현 안내](../solution/README.md)에 따라 `solution/`의 풀링과 시나리오 TODO를 완성합니다.
2. Python 참조 동일성 연산자 `is`로 같은 객체가 재사용되는지 확인합니다. 객체의 네 필드가 새 값으로 초기화되는지도 검사합니다.
3. Starter 루트에서 아래 명령으로 완성한 시나리오를 검증합니다. 시나리오는 검증기의 기본 제한 시간인 15초 안에 끝나도록 작성합니다.

```sh
node scripts/verify-protocol.mjs -- python -m framework.adapters.python --module solution.main
```

참가자는 JSON 직렬화와 stdin/stdout 처리를 작성할 필요가 없습니다. Python Runner가 [프로토콜 v1](PROTOCOL.md)의 입출력을 처리합니다. 로컬 Relay와 화면을 연결하는 절차는 [저장소 README](../README.md#3-relay와-webgl에서-시연하기)에 있습니다.

## 향후 언어 지원

다른 언어의 참가자 스타터와 Runner는 향후 지원 대상입니다. 언어별 구현이 추가될 때에도 [프로토콜 v1](PROTOCOL.md)은 공통 계약으로 사용합니다. 각 언어의 테스트는 객체나 저장 공간의 동일성을 해당 언어의 수명과 소유권 모델에 맞춰 검증해야 합니다.
