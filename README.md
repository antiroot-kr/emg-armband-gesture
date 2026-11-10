# EMG 팔찌 앱

ESP32-S3 팔찌로 팔 근육의 근전도(sEMG) 8채널을 녹화하고, 사용자에게 맞춘 손동작
인식 모델을 학습시킨 뒤, 팔찌가 손동작을 실시간으로 인식하게 하는 PC 앱(PyQt6)입니다.

| 문서 | 내용 |
|---|---|
| [README.md](README.md) (이 문서) | 전체 소개, 빠른 시작, 폴더 구성 |
| [INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md) | OS별 설치 방법과 설치 문제 해결 |
| [USER_GUIDE.md](docs/USER_GUIDE.md) | 앱 사용 순서와 녹화 요령 |
| [USER_GUIDE_DETAIL.md](docs/USER_GUIDE_DETAIL.md) | 모든 화면을 캡처와 함께 설명하는 상세 사용 설명서 (화면 요소, 경고 문구와 대처, 결과 읽는 법) |
| [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | 구조와 유지 보수 (개발자용) |

---

## 1. 하드웨어

| 항목 | 값 |
|---|---|
| 보드 | ESP32-S3 |
| 센서 | 근전도 8채널 |
| 통신 | BLE (기기 이름 `ESP32S3_FAST_BLE`) |
| 신호 | 1200Hz 샘플링(채널마다 1초에 1200번 측정), 10-bit ADC를 0~255 값으로 변환 |

인식하는 손동작(6가지): rest(휴식), flexion(손목 굽힘), extension(손목 폄),
close(주먹 쥐기), supination(손바닥 위로), pronation(손바닥 아래로).

---

## 2. 빠른 시작 (Windows)

자세한 설치 방법은 [INSTALLATION_GUIDE.md](docs/INSTALLATION_GUIDE.md)를 보세요.

1. 전달받은 폴더를 **영문으로만 된 경로**에 둡니다(예: `C:\emg\mandro-pc-app`).
   경로에 한글이 있으면 앱이 실행되지 않습니다.
2. **Python 3.10~3.12**를 설치합니다. 3.13은 쓸 수 없습니다.
3. 폴더 안의 [setup.bat](setup.bat)을 실행합니다. 가상환경(`.venv`)을 만들고 필요한 패키지를 설치합니다.
4. 앱을 실행합니다.
   ```powershell
   .venv\Scripts\python.exe client_app\main.py
   ```

macOS·Linux는 `setup.bat` 대신 [setup.sh](setup.sh)(`./setup.sh`)를 실행하고, `.venv/bin/python client_app/main.py`로 실행합니다.

---

## 3. 사용 흐름 (Phase 0~5)

각 화면을 그림과 함께 보려면 [USER_GUIDE_DETAIL.md](docs/USER_GUIDE_DETAIL.md)를 보세요.

| Phase (앱 화면 이름) | 하는 일 | 연결 |
|---|---|---|
| 0 Firmware | 팔찌 펌웨어 설치 | USB |
| 1 Capture | 피험자 정보 입력 → 캘리브레이션(5초간 팔에 힘 빼기) → 손동작 녹화 | BLE |
| 2 Training | 녹화한 데이터로 모델 학습 | — |
| 3 Install | 학습한 모델을 팔찌에 설치 | USB 또는 BLE |
| 4 Verify | 설치한 모델 확인 | BLE |
| 5 Score | 실시간 손동작 인식 | BLE |

**모델 설치 방법 (Phase 3)**

- **USB — "Install on bracelet" (처음 한 번):** 펌웨어 전체를 컴파일해서 올립니다.
  처음 설치할 때, 또는 펌웨어를 바꿨을 때 필요합니다. 1~2분 걸립니다.
- **BLE — "Send weights over BLE" (그다음부터):** 이미 펌웨어가 들어간 팔찌에 새로
  학습한 가중치만 무선으로 보냅니다. 몇 초면 끝납니다.

Phase 0과 Phase 3의 USB 설치는 같은 펌웨어를 올립니다. 어느 화면에서 설치해도 결과는 같습니다.
새로 설치한 펌웨어에는 모델이 비어 있으므로, BLE로 가중치를 한 번은 보내야 Phase 4·5에서 인식이 됩니다.

---

## 4. 폴더 구성

| 폴더 | 내용 |
|---|---|
| [client_app/](client_app/) | 앱 본체. 시작 파일은 [main.py](client_app/main.py) |
| [lib/](lib/) | 데이터 불러오기, 전처리, feature 계산, 학습, 평가, 펌웨어 업로드 |
| [scripts/](scripts/) | 학습·평가·내보내기를 앱 없이 실행하는 도구 |
| [firmware/esp32/exo_armband_hybrid_6clf/](firmware/esp32/exo_armband_hybrid_6clf/exo_armband_hybrid/) | **현재 팔찌 펌웨어** (앱이 올리는 것) |
| [firmware/esp32/](firmware/esp32/) 의 나머지 두 폴더 | 예전 펌웨어. 기록용으로만 남아 있고 쓰지 않음 |
| [firmware/teensy/](firmware/teensy/) | 모델을 펌웨어용 헤더로 바꾼 결과물(USB 설치 때 자동 생성) |
| [data/](data/) | 녹화 데이터. `data/<피험자>_BATCH<번호>/`에 CSV로 저장 |
| [user_guide_images/](docs/user_guide_images/) | [USER_GUIDE_DETAIL.md](docs/USER_GUIDE_DETAIL.md)에 쓰는 화면 캡처. 이름은 `<절 번호>_<순번>_<내용>.png` |
| [models/](models/) | 학습한 모델(`trained/*.keras`)과 scaler(`scalers/*.pkl`) |

### 데이터 형식

녹화 한 번(take)마다 CSV 파일 한 개가 생깁니다.

```
Time(ms), Raw_CH0..Raw_CH7, Amp_CH0..Amp_CH7, Label, Window
```

학습에는 `Raw_CH*` 값을 대역 통과 필터로 거른 뒤 128샘플 단위(윈도우)로 잘라 씁니다.
`Label`은 그 순간 하고 있던 동작 이름입니다.

---

## 5. 알려진 한계

- **앱이 보여 주는 학습 정확도는 실제보다 높게 나옵니다.** Phase 2 학습
  ([scripts/train_causal_concat.py](scripts/train_causal_concat.py))은 데이터를 섞은 뒤 학습용과 검증용으로 나눠서,
  서로 붙어 있는 구간이 양쪽에 들어갑니다. 실제 사용에 가까운 정확도는
  [scripts/train_multisession.py](scripts/train_multisession.py)(녹화 세션 단위로 나눠 검증)로 확인하세요.
- **BLE 수신 속도가 환경에 따라 떨어질 수 있습니다.** 목표는 1200Hz지만 거리,
  간섭, PC 블루투스 성능에 따라 900Hz 안팎까지 떨어질 수 있습니다. 앱을 실행한
  터미널의 `[BLE] ... Hz` 줄로 확인할 수 있습니다.
