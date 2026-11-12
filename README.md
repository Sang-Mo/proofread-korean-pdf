# proofread-korean-pdf

한글 PDF 도서·문서의 **맞춤법·띄어쓰기·교열 검사**와 **웹 검색 기반 팩트체크**를 병렬 서브에이전트로 수행하고, 검출된 항목을 **원본 PDF 문서 위에 하이라이트 + 스티키 노트(주석) 형태**로 직접 표시해 주는 AI 에이전트 스킬입니다.

[translate-book](https://github.com/deusyu/translate-book) 스킬의 병렬 청크 파이프라인 아키텍처를 기반으로 설계되었으며, **Claude Code**, **Codex CLI**, **Google Antigravity**, **OpenClaw** 등 다양한 에이전트 환경에서 범용으로 동작합니다.

---

## 주요 기능 (Features)

1. **페이지 추적형 청크 분할 (`extract_pdf.py`)**
   - PDF에서 텍스트를 추출할 때 `<!-- PAGE: N -->` 마커를 보존하고, PDF 줄바꿈으로 인해 어절 중간에 끊어진 문장(예: `들렸\n다`)을 자연스럽게 복원하여 문맥 손실 없이 `chunk0001.md`, `chunk0002.md`...로 분할합니다.
2. **병렬 서브에이전트 교정·교열 및 팩트체크**
   - 각 청크를 독립된 서브에이전트가 전담하여 컨텍스트 누적으로 인한 누락을 방지합니다.
   - **한글 맞춤법·교열 (`spelling`)**: 국립국어원 어문 규범(한글 맞춤법, 표준어 규정, 외래어 표기법, 띄어쓰기, 문장 호응) 기준으로 오류를 검출합니다.
   - **팩트체크 (`fact_check`)**: 역사적 연도·사건, 실존 인물·기관·지명, 과학/법률/경제 사실, 인용문 및 전후 설정 모순을 웹 검색 도구로 교차 검증합니다.
3. **줄바꿈 대응 정밀 PDF 하이라이트 & 노트 주석 (`annotate_pdf.py`)**
   - PyMuPDF(`rawdict`) 글자 단위 바운딩 박스 스트림 매칭을 사용하여, PDF에서 두 줄에 걸쳐 줄바꿈된 어구도 정확히 찾아 하이라이트와 팝업 스티키 노트를 부착합니다.
   - **맞춤법/교열**: 노란색 하이라이트 + 코멘트 노트 (`[맞춤법/교열] 원문 / 수정 제안 / 검토 의견`)
   - **팩트체크**: 코랄/적색 하이라이트 + 팩트체크 노트 (`[팩트체크 검토] 원문 / 수정 제안 / 검토 의견 / 참고 출처`)
4. **중단 후 재개 지원 (`run_state.py`)**
   - `manifest.json` 및 `run_state.json`의 SHA-256 해시 추적을 통해 대용량 단행본 PDF 작업 중 중단되더라도 완료된 청크는 건너뛰고 남은 청크만 이어서 검수합니다.
5. **종합 마크다운 보고서 자동 생성**
   - 주석이 달린 PDF(`{파일명}_checked.pdf`)와 함께 전체 검출 내역을 표와 목록으로 정리한 `{파일명}_proofread_report.md`를 생성합니다.

---

## 동작 구조 (How It Works)

```
입력 한글 PDF (book.pdf)
  │
  ▼
extract_pdf.py (PyMuPDF)
  │  페이지 마커(<!-- PAGE: N -->) 보존 + 줄바꿈 복원
  │  chunk0001.md, chunk0002.md, ... + manifest.json 생성
  ▼
병렬 서브에이전트 검수 (기본 6개 동시 실행)
  │  1) 국립국어원 어문 규범 기반 한글 맞춤법·띄어쓰기·문법 검사
  │  2) 웹 검색(WebSearch / search_web) 기반 팩트체크
  │  issues_chunk0001.json, issues_chunk0002.json, ... 생성
  ▼
annotate_pdf.py (검증 및 PDF 주석 주입)
  │  글자 단위 좌표 매칭 → PDF 본문 하이라이트 + 스티키 노트(주석) 삽입
  ▼
출력물 생성
  ├── {파일명}_checked.pdf          (노트/하이라이트가 표시된 PDF, 또는 --in-place로 원본 직접 마킹)
  └── {파일명}_proofread_report.md  (전체 맞춤법·팩트체크 종합 보고서)
```

---

## 사전 준비 사항 (Prerequisites)

- **Python 3.9+**
- **[uv](https://docs.astral.sh/uv/)** (권장 — 별도 패키지 설치 없이 `uv run --with pymupdf`로 즉시 실행 가능)
  - 만약 `uv`를 사용하지 않는다면 아래 명령어로 `pymupdf`만 설치하면 됩니다:
    ```bash
    python3 -m pip install pymupdf
    ```

---

## 설치 방법 (Installation)

사용 중인 AI 에이전트에 맞춰 아래 명령어로 설치하세요.

### 1. Claude Code

```bash
mkdir -p ~/.claude/skills
git clone https://github.com/Sang-Mo/proofread-korean-pdf.git ~/.claude/skills/proofread-korean-pdf
```

또는 `npx skills` CLI 사용 시:
```bash
npx skills add Sang-Mo/proofread-korean-pdf -a claude-code -g
```

### 2. Codex CLI

```bash
mkdir -p ~/.agents/skills
git clone https://github.com/Sang-Mo/proofread-korean-pdf.git ~/.agents/skills/proofread-korean-pdf
```

또는 `npx skills` CLI 사용 시:
```bash
npx skills add Sang-Mo/proofread-korean-pdf -a codex -g
```

### 3. Google Antigravity

```bash
mkdir -p ~/.gemini/config/skills
git clone https://github.com/Sang-Mo/proofread-korean-pdf.git ~/.gemini/config/skills/proofread-korean-pdf
```

### 4. OpenClaw

```bash
openclaw skills install @Sang-Mo/proofread-korean-pdf
```

---

## 사용 예시 (Usage)

에이전트 채팅창에서 아래와 같이 요청하세요:

```text
/proofread-korean-pdf ./원고.pdf
```

또는 자연어로 요청할 수 있습니다:

```text
"./원고.pdf 파일을 proofread-korean-pdf 스킬로 맞춤법 검사하고 내용 중 팩트체크할 부분을 검색해서 PDF에 노트로 체크해줘."
```

원본 PDF 파일 자체에 바로 노트를 덮어쓰고 싶다면(원본은 `.orig.pdf`로 자동 백업됨):

```text
"./원고.pdf 파일을 맞춤법 및 팩트체크해서 원본 PDF에 직접 노트를 추가해줘 (--in-place)."
```

---

## 스크립트 직접 실행 레퍼런스 (CLI Reference)

1. **PDF 추출 및 청크 분할**
   ```bash
   uv run --with pymupdf python3 scripts/extract_pdf.py "원고.pdf" --chunk-size 5000
   ```
2. **검수 진행 상태 확인 (`plan` / `record` / `status`)**
   ```bash
   python3 scripts/run_state.py plan "원고_proofread_temp"
   python3 scripts/run_state.py status "원고_proofread_temp"
   ```
3. **인접 청크 문맥 출력**
   ```bash
   python3 scripts/chunk_context.py "원고_proofread_temp" "chunk0002.md"
   ```
4. **PDF 주석(하이라이트+노트) 기록 및 보고서 생성**
   ```bash
   uv run --with pymupdf python3 scripts/annotate_pdf.py \
     --pdf "원고.pdf" \
     --temp-dir "원고_proofread_temp" \
     --output-pdf "원고_checked.pdf" \
     --report-md "원고_proofread_report.md"
   ```

---

## 라이선스 (License)

MIT License
