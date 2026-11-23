# Java Object Pooling 스타터

JDK 21과 Node.js 22 이상을 사용합니다. 아래 명령은 Starter 저장소 루트에서 실행합니다. Maven Central에서 Gson 2.13.2를 내려받아 Runner의 JSON 처리에 사용합니다. 빌드 결과와 JAR는 Git에서 제외되는 `build/java/`에 저장됩니다.

## 빌드 및 검증

### Windows PowerShell

```powershell
java -version
javac -version
node --version
New-Item -ItemType Directory -Force build/java | Out-Null
$jar = 'build/java/gson-2.13.2.jar'
Invoke-WebRequest 'https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.13.2/gson-2.13.2.jar' -UseBasicParsing -OutFile $jar
$sources = (Get-ChildItem framework/adapters/java,solution/java,tests/java,tests/fixtures/java -Filter *.java).FullName
javac --release 21 -encoding UTF-8 -cp $jar -d build/java $sources
$env:GALAXY_JAVA_CLASSPATH = "build/java;$jar"
java -cp $env:GALAXY_JAVA_CLASSPATH galaxy.runner.RunnerTests
node --test tests/java/transport.test.mjs
node scripts/verify-protocol.mjs -- java -cp $env:GALAXY_JAVA_CLASSPATH galaxy.fixture.Demo
node scripts/verify-protocol.mjs -- java -cp $env:GALAXY_JAVA_CLASSPATH galaxy.fixture.Demo --reset-on-start
```

### POSIX 셸

```sh
java -version
javac -version
node --version
mkdir -p build/java
jar=build/java/gson-2.13.2.jar
curl -fL 'https://repo.maven.apache.org/maven2/com/google/code/gson/gson/2.13.2/gson-2.13.2.jar' -o "$jar"
javac --release 21 -encoding UTF-8 -cp "$jar" -d build/java \
  framework/adapters/java/*.java solution/java/*.java tests/java/*.java tests/fixtures/java/*.java
export GALAXY_JAVA_CLASSPATH="build/java:$jar"
java -cp "$GALAXY_JAVA_CLASSPATH" galaxy.runner.RunnerTests
node --test tests/java/transport.test.mjs
node scripts/verify-protocol.mjs -- java -cp "$GALAXY_JAVA_CLASSPATH" galaxy.fixture.Demo
node scripts/verify-protocol.mjs -- java -cp "$GALAXY_JAVA_CLASSPATH" galaxy.fixture.Demo --reset-on-start
```

검증기에서 기본 데모는 3개 이벤트, reset을 켠 데모는 4개 이벤트로 통과합니다. 두 실행 모두 acquire 2회, release 1회, 재사용 1회로 끝나며 화면에 남는 객체는 1개입니다. Java 테스트는 실제 객체 참조가 `==`인지, 네 필드가 모두 새 값인지, 잘못된 대여에 대한 호출이 차단되는지 검사합니다.

## 참가자 코드 완성하기

1. [CosmicObject.java](CosmicObject.java)에 상태와 재초기화 로직을 작성합니다. `snapshot()`은 실제 객체의 이름, 타입, 색상, 크기를 읽어 불변 `Runner.CosmicSpec`으로 반환합니다.
2. [ObjectPool.java](ObjectPool.java)에서 보관 공간과 용량 정책을 정합니다. `acquire(spec)`는 사용 가능한 인스턴스를 확보하고 초기화한 뒤 그 참조를 반환합니다. `release(storage)`는 해당 풀에서 현재 대여 중인 객체만 받아 다시 사용할 수 있게 합니다. 두 연산이 예외를 던질 때는 풀의 상태가 유지되도록 설계합니다.
3. [Main.java](Main.java)에서 `context.acquire(spec)` → `context.snapshot(lease)` → `context.release(lease)` → 새 값으로 재확보를 구현합니다. 반환된 대여는 같은 객체를 다시 확보한 후에도 만료 상태입니다. 반환 전에 얻은 불변 스냅샷은 이전 값을 그대로 보관합니다.
4. 자신이 만든 풀을 직접 테스트합니다. `==`로 실제 인스턴스 재사용을 확인하고 재초기화, 중복 반환, 다른 풀 객체의 반환, 용량 한도를 검사하세요. 코드를 다시 컴파일한 뒤 공통 검증기로 시나리오를 확인합니다.

**Windows PowerShell**

```powershell
node scripts/verify-protocol.mjs -- java -cp $env:GALAXY_JAVA_CLASSPATH galaxy.solution.Main
```

**POSIX 셸**

```sh
node scripts/verify-protocol.mjs -- java -cp "$GALAXY_JAVA_CLASSPATH" galaxy.solution.Main
```

## Relay 및 WebGL 시연

[Starter의 Relay 및 WebGL 안내](../../README.md#3-relay와-webgl에서-시연하기)에 따라 플랫폼을 시작합니다. 아래 명령은 두 저장소가 같은 상위 폴더에 있는 경우입니다. 경로가 다르면 실제 Bridge 경로를 사용하세요.

**Windows PowerShell**

```powershell
$env:GALAXY_PARTICIPANT_ID = 'my_java_id'
$env:GALAXY_WS = 'ws://127.0.0.1:8787/ws'
$env:GALAXY_TOKEN = 'local-demo-token'
node ../Galaxy-Expansion/bridge/local-bridge.mjs -- java -cp $env:GALAXY_JAVA_CLASSPATH galaxy.fixture.Demo
```

**POSIX 셸**

```sh
GALAXY_PARTICIPANT_ID=my_java_id GALAXY_WS=ws://127.0.0.1:8787/ws GALAXY_TOKEN=local-demo-token \
  node ../Galaxy-Expansion/bridge/local-bridge.mjs -- java -cp "$GALAXY_JAVA_CLASSPATH" galaxy.fixture.Demo
```

처음에는 고유한 참가자 ID를 사용합니다. Relay가 연결 종료 후에도 슬롯을 보관하므로 같은 ID에서 기존 상태를 지우려면 Java 메인 클래스 뒤에 `--reset-on-start`를 붙입니다. Runner가 `reset`의 응답을 받은 다음에 시나리오를 시작합니다. 원격 토큰은 Bridge 환경 변수에 설정하고 저장소에 커밋하지 마세요.

## 실행 범위

- Runner가 실제 참조와 유효한 대여를 추적하고 슬롯당 세대를 부여합니다. 참가자 코드는 시나리오 호출 스레드에서 동기적으로 실행합니다.
- Runner 시작 후 `System.out`은 stderr로 연결됩니다. 메인 함수의 Runner 호출 전을 포함해 참가자 진단은 처음부터 `System.err`로 보내세요. Bridge가 인증 및 네트워크 연결을 처리합니다.
- Runner는 초기 메시지에 5초, 이벤트 응답에 2초를 기다립니다. 전송 간격은 최소 25ms입니다. 세션당 서로 다른 슬롯 최대 500개와 메시지당 8,000 UTF-8 바이트 한도를 적용합니다.
- 검증기는 기본 15초 안에 종료되는 유한한 시나리오를 요구합니다. 응답 오류나 전송 시간 초과가 나면 Runner는 비정상 종료합니다. 실패한 이벤트의 재전송이나 종료 시 자동 반환은 수행하지 않습니다.
