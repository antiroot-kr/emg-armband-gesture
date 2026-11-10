# 설치 가이드

전달받은 앱 폴더를 PC에 설치하는 방법입니다. Windows를 기준으로 설명하고,
macOS·Ubuntu는 차이 나는 부분만 따로 적었습니다.

---

## 1. 설치할 것 한눈에 보기

| 구성 요소 | 용도 | 필수 여부 |
|---|---|---|
| Python 3.10~3.12 | 앱 실행, 모델 학습 | 필수 |
| Python 패키지 ([requirements.txt](../requirements.txt)) | 앱이 쓰는 라이브러리 | 필수 (`setup.bat`이 설치) |
| arduino-cli + ESP32 코어 + Adafruit 라이브러리 | 팔찌 펌웨어 컴파일·설치 (Phase 0, 3) | USB로 펌웨어를 올릴 때 필수 |
| USB 시리얼 드라이버 | PC가 팔찌를 USB 포트로 인식 | 필요한 경우만 |
| PC 블루투스 (BLE 지원, 켜져 있어야 함) | 녹화·모델 전송·실시간 인식 (Phase 1, 3, 4, 5) | 필수. 노트북 대부분은 내장. 없으면 USB 블루투스 동글 |
| Microsoft Visual C++ 재배포 패키지 (x64) | TensorFlow 실행 | Windows, 오류가 날 때만 |

> **Python 3.13은 쓰지 마세요.** Windows용 TensorFlow가 3.13을 지원하지 않습니다.

---

## 2. Windows 설치

### 2-1. 폴더를 영문 경로에 두기

전달받은 폴더를 **한글이 없는 경로**에 복사합니다. 예:

```
C:\emg\mandro-pc-app
```

`C:\Users\홍길동\바탕 화면\...`처럼 경로에 한글이 있으면 인코딩 오류(cp949)로 앱과
펌웨어 컴파일이 실패합니다. 영문 경로로 옮기는 것만이 확실한 해결책입니다.

### 2-2. Python 설치

1. python.org에서 **Python 3.12 (64-bit)**를 내려받아 설치합니다.
   설치 첫 화면에서 **"Add python.exe to PATH"를 꼭 체크**하세요.
   (또는 `winget install Python.Python.3.12`)
2. 확인:
   ```powershell
   py -3.12 --version
   ```

### 2-3. arduino-cli 설치 (펌웨어 설치용)

USB로 팔찌에 펌웨어를 올리려면 필요합니다. 아래 중 하나로 설치합니다.

```powershell
winget install ArduinoSA.CLI
```

또는 arduino-cli 공식 릴리스 페이지에서 Windows용 zip을 내려받아 `arduino-cli.exe`를
폴더(예: `C:\tools\arduino-cli\`)에 풀고 그 폴더를 PATH에 추가합니다.

설치 후 **PowerShell 창을 새로 열어야** `arduino-cli` 명령이 잡힙니다. 확인:

```powershell
arduino-cli version
```

> arduino-cli는 **setup.bat보다 먼저** 설치하세요. setup.bat이 arduino-cli를 찾아야 ESP32 코어를 함께 설치합니다. 순서를 바꿨다면 arduino-cli 설치 후 setup.bat을 한 번 더 실행하면 됩니다.

### 2-4. setup.bat 실행

앱 폴더에서 PowerShell을 열고 실행합니다.

```powershell
cd C:\emg\mandro-pc-app
.\setup.bat
```

[setup.bat](../setup.bat)이 하는 일:

- 설치된 Python 3.10~3.12를 찾아 가상환경(`.venv`)을 만듭니다.
- `requirements.txt`의 패키지를 설치합니다.
- arduino-cli가 있으면 ESP32 보드 지원(코어)을 설치합니다. 이때 arduino-cli의
  데이터 폴더를 `C:\Arduino15`(영문 경로)로 고정해서, Windows 사용자 이름이 한글이어도
  컴파일 오류가 나지 않게 합니다. 처음에는 200~300MB를 내려받느라 몇 분 걸립니다.

### 2-5. Adafruit 라이브러리 설치

펌웨어 컴파일에 필요합니다. `setup.bat`이 설치하지 않으므로 따로 실행합니다.

```powershell
arduino-cli lib install "Adafruit NeoPixel" "Adafruit Unified Sensor" "Adafruit BNO055"
```

### 2-6. USB 연결 확인

팔찌를 USB로 꽂고 **장치 관리자 → 포트(COM & LPT)**를 엽니다.

- `COM3` 같은 항목이 보이면 준비 끝입니다.
- 아무것도 없거나 노란 경고 표시가 있으면, 보드 칩에 맞는 USB 시리얼 드라이버
  (**CP210x** 또는 **CH340**)를 설치합니다. ESP32-S3는 드라이버가 필요 없는 경우가 많으니
  먼저 다시 꽂아 보세요.
- 드라이버 없이도 안 보이면 데이터 전송이 되는 케이블인지(충전 전용 케이블은 안 됨) 확인하세요.

### 2-7. 앱 실행

```powershell
.venv\Scripts\python.exe client_app\main.py
```

가상환경을 켜고 실행해도 됩니다.

```powershell
.venv\Scripts\Activate.ps1
python client_app\main.py
```

`Activate.ps1` 실행이 막히면(실행 정책 오류) 먼저 아래를 실행하세요. 지금 창에서만 허용됩니다.

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

---

## 3. macOS 설치

```bash
# 1) 도구 설치
brew install python@3.12 arduino-cli

# 2) 앱 폴더로 이동 후 설치 스크립트 실행 (가상환경, 패키지, ESP32 코어)
cd ~/emg/mandro-pc-app
./setup.sh

# 3) 펌웨어 라이브러리
arduino-cli lib install "Adafruit NeoPixel" "Adafruit Unified Sensor" "Adafruit BNO055"

# 4) 실행
.venv/bin/python client_app/main.py
```

- macOS는 경로에 한글이 있어도 문제없습니다.
- 팔찌 USB 포트는 보통 자동으로 잡히며 `/dev/cu.usbmodem*` 또는 `/dev/cu.usbserial-*`로 보입니다.

---

## 4. Ubuntu 설치

```bash
# 1) 도구 설치
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3-pip
curl -fsSL https://raw.githubusercontent.com/arduino/arduino-cli/master/install.sh | sh

# 2) USB 포트 권한 (설정 후 로그아웃했다가 다시 로그인)
sudo usermod -a -G dialout $USER

# 3) 앱 폴더로 이동 후 설치 스크립트 실행
cd ~/emg/mandro-pc-app
./setup.sh

# 4) 펌웨어 라이브러리
arduino-cli lib install "Adafruit NeoPixel" "Adafruit Unified Sensor" "Adafruit BNO055"

# 5) 실행
.venv/bin/python client_app/main.py
```

팔찌 USB 포트는 `/dev/ttyUSB0` 또는 `/dev/ttyACM0`으로 보입니다.

---

## 5. 설치 확인 목록

- [ ] `arduino-cli version`이 실행된다
- [ ] `arduino-cli core list`에 `esp32:esp32`가 보인다
- [ ] `arduino-cli lib list`에 Adafruit 라이브러리 3개가 보인다 (함께 설치되는 BusIO까지 4개로 보여도 정상)
- [ ] `.venv\Scripts\python.exe -c "import tensorflow"`가 오류 없이 끝난다
- [ ] 팔찌를 꽂으면 COM 포트(또는 `/dev/tty*`)로 보인다
- [ ] Windows 설정에서 블루투스가 켜져 있다
- [ ] 앱이 열린다
- [ ] Phase 0에서 펌웨어 설치가 끝까지 된다

---

## 6. 설치 문제 해결

| 증상 | 원인과 해결 |
|---|---|
| `pip install`에서 TensorFlow를 찾을 수 없다 | Python 3.13을 쓰고 있습니다. 3.12를 설치하고 `.venv` 폴더를 지운 뒤 `setup.bat`을 다시 실행하세요. |
| `import tensorflow`에서 DLL 오류 | Visual C++ 재배포 패키지가 없습니다. `winget install Microsoft.VCRedist.2015+.x64` |
| `UnicodeDecodeError` / `UnicodeEncodeError` | 경로에 한글이 있습니다. 앱 폴더를 영문 경로로 옮기세요. |
| `python client_app\main.py`를 실행하면 "Python"만 뜨고 끝난다 | 가상환경 밖의 Python이 실행됐습니다. `.venv\Scripts\python.exe`로 실행하세요. |
| 펌웨어 컴파일 중 `cc1plus.exe: out of memory` | PC 메모리가 부족합니다. 브라우저 등 다른 프로그램을 닫고 다시 시도하세요. |
| 모델 학습(Phase 2) 중 오류 메시지 없이 로그가 끊긴다 | 메모리가 부족해 학습이 강제로 종료됐을 가능성이 큽니다. 다른 프로그램을 닫고 다시 시도하세요. 학습 로그는 Windows에서 `%TEMP%\phase2_training.log`에 있습니다. |
| Phase 3 USB 설치가 `Connecting…`에서 멈춘다 | 팔찌를 부트로더 모드로 바꿉니다: **BOOT**를 누른 채 **RESET**을 눌렀다 떼고, **BOOT**를 뗍니다. 그다음 다시 시도하세요. |
