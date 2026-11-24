# OPIc Coach 🎙️

OPIc 시험 연습용 영어 말하기 앱이에요. 집 윈도우 PC에서 서버를 돌리고, 안드로이드 폰에서는 앱처럼 설치해서 씁니다.

- 난이도(1~6)와 Background Survey 주제에 맞춰 질문을 랜덤으로 출제
- 질문은 실제 시험처럼 소리로 들려줌 (TTS)
- 마이크로 영어 답변 → 글자로 변환 (Chrome 음성 인식)
- OpenAI(ChatGPT) AI 피드백: 예상 등급, 문법 교정, 더 좋은 표현, 구성·길이, 모범 답안
- 연습 기록은 폰에 저장

```
[안드로이드 Chrome 앱]  ── HTTPS (Tailscale) ──>  [집 윈도우 PC: Python 서버]  ──>  OpenAI API
```

---

## 1. 윈도우 PC 준비 (처음 한 번)

1. **Python 설치**: https://www.python.org/downloads/ 에서 설치합니다. 설치 화면의 **"Add python.exe to PATH"** 를 꼭 체크하세요.
2. **이 저장소 받기**: GitHub에서 Code → Download ZIP으로 받아 압축을 풀거나 `git clone` 하세요.
3. `opic_coach` 폴더의 **`setup_windows.bat`** 을 더블클릭합니다. 가상환경을 만들고 필요한 패키지를 설치해요.
4. **API 키 넣기**
   - https://platform.openai.com/api-keys 에서 API 키를 발급합니다. Billing 메뉴에서 크레딧을 충전해야 동작해요. ChatGPT Plus 구독과는 별개예요.
   - `opic_coach\.env` 파일을 메모장으로 열어 `OPENAI_API_KEY=` 뒤에 키를 붙여넣고 저장합니다.
   - `.env` 는 `.gitignore` 에 들어 있어서 GitHub에 올라가지 않아요.
5. **`run_windows.bat`** 을 더블클릭하면 서버가 켜집니다. 이 창이 열려 있는 동안만 앱을 쓸 수 있어요.
   - PC 브라우저에서 http://localhost:8000 을 열어 화면이 나오면 성공입니다.
   - 윈도우 방화벽 허용 창이 뜨면 "허용"을 누르세요.

## 2. 폰에서 접속하기: Tailscale (추천)

**왜 필요한가요?** 안드로이드 Chrome은 마이크와 앱 설치를 **HTTPS 주소에서만** 허용해요. `http://192.168.x.x:8000` 같은 집 내부 주소로는 마이크가 막힙니다. Tailscale을 쓰면 무료로 HTTPS 주소가 생기고, 밖에서 LTE로도 내 PC에 안전하게 접속할 수 있어요. 인터넷에 공개되지 않고 내 기기끼리만 연결됩니다.

1. PC와 폰 모두에 Tailscale을 설치하고 **같은 계정**으로 로그인합니다.
   - PC: https://tailscale.com/download/windows
   - 폰: Play 스토어에서 "Tailscale" 설치
2. Tailscale 관리 페이지 https://login.tailscale.com/admin/dns 에서 **MagicDNS** 와 **HTTPS Certificates** 를 켭니다.
3. PC에서 서버를 켠 상태로 **명령 프롬프트(cmd)** 를 열고 한 번만 실행합니다.
   ```
   tailscale serve --bg 8000
   ```
   출력에 `https://내PC이름.tail1234.ts.net` 같은 주소가 나와요. `--bg` 덕분에 재부팅해도 설정이 유지됩니다.
4. 폰 Chrome에서 그 주소를 엽니다. 마이크 권한을 물으면 **허용**을 누르세요.
5. Chrome 메뉴(⋮)에서 **"홈 화면에 추가"** 또는 **"앱 설치"** 를 누르면 앱 아이콘이 생깁니다.

> **집 와이파이에서만 쓸 거라면 (대안)**: 폰 Chrome 주소창에 `chrome://flags/#unsafely-treat-insecure-origin-as-secure` 를 열고, `http://PC의IP:8000` 을 입력한 뒤 Enabled로 바꾸고 재시작하세요. PC IP는 cmd에서 `ipconfig` 를 실행하면 나오는 IPv4 주소입니다. 이 방법은 앱 설치가 잘 안 될 수 있어서 Tailscale을 추천해요.

## 3. 사용법

1. **설정** 탭에서 난이도와 주제를 고릅니다.
   - 난이도 1~2: 자기소개, 묘사, 루틴
   - 난이도 3: 과거 경험 추가
   - 난이도 4: 비교, 롤플레이 추가
   - 난이도 5~6: 사회적 이슈 추가
2. **연습** 탭에서 **새 질문**을 누르면 질문이 소리로 나오고, 끝나면 자동으로 녹음이 시작돼요.
3. 영어로 답하고 **답변 끝내기**를 누릅니다. 인식이 틀린 단어는 직접 고칠 수 있어요.
4. **피드백 받기**를 누르면 10~30초 뒤에 결과가 나옵니다. 모범 답안은 소리로도 들을 수 있어요.

## 4. 비용과 설정

- 기본 모델은 `gpt-5.4-mini`, 피드백 깊이(`reasoning_effort`)는 `low` 로 빠르게 설정돼 있어요.
- OpenAI 모델은 자주 바뀌고 오래된 모델은 종료돼요. https://platform.openai.com/docs/models 에서 최신 모델 이름을 확인하고 `.env` 의 `OPIC_MODEL` 에 넣으세요.
  - 모델은 **Structured Outputs(JSON schema)** 를 지원해야 해요. 최근 GPT 모델은 대부분 지원합니다.
- 피드백 1회 비용은 mini 모델 기준 몇 원 수준이에요. 정확한 사용량은 OpenAI 대시보드의 Usage에서 확인하세요.
- `.env` 에서 바꿀 수 있는 값:
  - `OPIC_MODEL=...`: 더 좋은(비싼) 모델이나 더 싼 모델로 바꿀 수 있어요.
  - `OPIC_EFFORT=medium` 또는 `high`: 더 자세한 피드백을 받지만 느려져요. 추론 모델이 아니면 이 값은 자동으로 무시돼요.
- 설정의 "AI가 새 질문 만들기"를 켜면 질문마다 API 호출이 한 번 더 일어나요. 끄면 내장 질문 은행(56문항)에서 무료로 출제됩니다.

## 5. 문제 해결

| 증상 | 해결 |
|---|---|
| "서버에 연결할 수 없어요" | PC에서 `run_windows.bat` 창이 켜져 있는지, 폰의 Tailscale이 연결돼 있는지 확인하세요. |
| 마이크가 안 됨 | HTTPS 주소인지 확인하세요. 주소창 자물쇠 → 권한 → 마이크 허용. |
| 질문 소리가 안 나옴 | 폰 미디어 볼륨을 올리세요. 안드로이드 설정 → 텍스트 음성 변환에서 Google 엔진과 영어 음성을 설치하세요. |
| "API 키가 올바르지 않아요" | `.env` 의 `OPENAI_API_KEY` 를 확인하고 서버를 껐다 켜세요. |
| "모델을 찾을 수 없어요" | 모델이 종료됐거나 이름이 틀렸어요. `.env` 의 `OPIC_MODEL` 을 최신 모델로 바꾸세요. |
| "크레딧이 부족해요" | OpenAI Billing 페이지에서 크레딧을 충전하세요. |
| PC가 절전 모드로 들어감 | 윈도우 설정 → 전원에서 절전 모드를 "안 함"으로 바꾸세요. |

## 개발용

```
cd opic_coach
python -m pytest -q test_opic.py
```

- 질문 추가: `questions.py` 의 `_RAW` 목록에 `(주제, 유형, 질문)` 을 추가하세요.
- 피드백 기준 수정: `coach.py` 의 `SYSTEM_FEEDBACK` 을 고치세요.
