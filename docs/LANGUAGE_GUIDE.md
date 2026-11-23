# 언어 가이드

한 가지 언어를 골라 해당 안내의 데모, 빌드, 테스트 명령을 실행합니다. Node.js 22 이상은 공통 검증기와 로컬 플랫폼에 사용합니다.

| 언어 | 개발 도구 | 저장 공간 재사용을 확인하는 방법 |
| --- | --- | --- |
| [Python](../solution/README.md) | Python 3.12 | 객체를 `is`로 비교 |
| [C++](../solution/cpp/README.md) | C++20 컴파일러, CMake | 수명이 유지되는 저장 공간의 주소 비교 |
| [Java](../solution/java/README.md) | JDK 21 | 인스턴스 참조를 `==`로 비교 |
| [C#](../solution/csharp/README.md) | .NET 8 SDK | 인스턴스 참조를 `ReferenceEquals`로 비교 |
| [Rust](../solution/rust/README.md) | stable Rust, Cargo | 재대여한 핸들이 같은 저장 공간을 가리키는지 확인 |

## Python에서 시작하기

1. [Python 구현 안내](../solution/README.md)에 따라 `solution/`의 풀링과 시나리오 TODO를 완성합니다.
2. Python 참조 동일성 연산자 `is`로 같은 객체가 재사용되는지 확인합니다. 객체의 네 필드가 새 값으로 초기화되는지도 검사합니다.
3. Starter 루트에서 아래 명령으로 완성한 시나리오를 검증합니다. 시나리오는 검증기의 기본 제한 시간인 15초 안에 끝나도록 작성합니다.

```sh
node scripts/verify-protocol.mjs -- python -m framework.adapters.python --module solution.main
```

참가자는 JSON 직렬화와 stdin/stdout 처리를 작성할 필요가 없습니다. Python Runner가 [프로토콜 v1](PROTOCOL.md)의 입출력을 처리합니다. 로컬 Relay와 화면을 연결하는 절차는 [저장소 README](../README.md#3-relay와-webgl에서-시연하기)에 있습니다.

모든 Runner는 [프로토콜 v1](PROTOCOL.md)을 사용합니다. 참가자 시나리오는 언어별 컨텍스트를 통해 풀을 호출하고, 실제 객체나 저장 공간의 재사용은 언어별 테스트로 확인합니다.
