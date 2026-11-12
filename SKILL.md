---
name: proofread-korean-pdf
description: Proofread Korean PDF books and documents using parallel sub-agents (modeled on translate-book). Checks Korean spelling, spacing, grammar, and terminology consistency across chunks, performs web-search fact-checking on verifiable claims, and writes sticky notes & highlight annotations directly onto the PDF alongside a Markdown summary report. Use when asked to check Korean spelling/grammar (맞춤법·교정·교열), fact-check (팩트체크), or annotate issues as notes on a Korean PDF document.
allowed-tools: Read, Write, Edit, Bash, Glob, Grep, Agent, Task, WebSearch, WebFetch, AskUserQuestion
metadata: {"openclaw":{"requires":{"bins":["python3"]},"optionalBins":["uv"]},"homepage":"https://github.com/Sang-Mo/proofread-korean-pdf"}
---

# Korean PDF Proofreading & Fact-Checking Skill (`proofread-korean-pdf`)

You are a Korean publication proofreader and fact-checker. Modeled on the `translate-book` parallel chunk pipeline, this skill processes a Korean PDF document by splitting it into page-tracked chunks, running parallel sub-agents to inspect **Korean spelling/spacing/grammar (맞춤법·띄어쓰기·교열)** and **factual accuracy (팩트체크)** via web search, and annotating every issue directly onto the PDF as **Highlight + Sticky Note (주석/노트)** annotations.

This skill is platform-neutral and works across **Claude Code**, **Codex**, **Antigravity**, and **OpenClaw**.

> **Path Resolution (`{baseDir}`)**: Throughout this file, `{baseDir}` refers to the directory containing this `SKILL.md` file (e.g., `~/.claude/skills/proofread-korean-pdf`, `~/.agents/skills/proofread-korean-pdf`, or `~/.gemini/config/skills/proofread-korean-pdf`). If your runtime does not automatically interpolate `{baseDir}`, replace it with the actual directory path where this `SKILL.md` is located.
>
> **Python Runner**: Commands below use `uv run --with pymupdf python3` so they work zero-config when `uv` is installed. If `uv` is not installed on the system, run `python3 -m pip install pymupdf` once and invoke `python3` directly.

---

## Workflow

### 1. Collect Parameters

Determine the following from the user's message:
- **`pdf_path`**: Path to the input Korean PDF file — **REQUIRED**
- **`output_pdf`**: Output annotated PDF path (default: `{filename}_checked.pdf` in the same directory or workspace)
- **`in_place`**: Whether to write annotations directly onto the original PDF file (`--in-place`, which backs up the untouched original to `{filename}.orig.pdf` and updates `<pdf_path>` in place)
- **`chunk_size`**: Target character size per chunk (default: `5000`)
- **`concurrency`**: Number of parallel sub-agents per batch (default: `6`)
- **`temp_root`**: Optional directory under which `{filename}_proofread_temp/` should be created
- **`custom_instructions`**: Any specific style guide, domain rules, or fact-check focus areas from the user (optional)

If `pdf_path` is not provided, ask the user.

---

### 2. Preprocess — Extract Page-Tracked Markdown Chunks

Run `extract_pdf.py` to extract text from the PDF while preserving exact `<!-- PAGE: N -->` markers and unwrapping mid-word line breaks:

```bash
uv run --with pymupdf python3 "{baseDir}/scripts/extract_pdf.py" "<pdf_path>" --chunk-size 5000
```
*(Fallback if `uv` is unavailable: `python3 "{baseDir}/scripts/extract_pdf.py" "<pdf_path>" --chunk-size 5000`)*

If the user provided `temp_root`, add `--temp-root "<temp_root>"`.

This creates `{filename}_proofread_temp/` containing:
- `input.md` — Full extracted text with `<!-- PAGE: N -->` markers
- `chunk0001.md`, `chunk0002.md`, ... — Page-aware source chunks for proofreading
- `manifest.json` — Chunk manifest with page ranges (`pages`), character counts, and SHA-256 hashes
- `source_fingerprint.json` — SHA-256 identity of the source PDF
- `config.txt` — Pipeline metadata

---

### 3. Build Term & Style Sheet (Optional Consistency Check)

Just as `translate-book` builds a `glossary.json` to prevent term drift across chunks, check whether recurring proper nouns, character names, or specialized terms have inconsistent spelling across the document:

1. Sample `chunk0001.md`, a middle chunk, and the last chunk.
2. Identify key recurring names, terms, or formatting conventions and save them to `<temp_dir>/style_guide.json` if needed:
   ```json
   {
     "terms": [
       {"canonical": "표준 표기", "variants_to_flag": ["오표기1", "오표기2"], "note": "용어 통일"}
     ]
   }
   ```

---

### 4. Plan Selective Proofreading

Run `run_state.py plan` to see which chunks need inspection (supports resuming interrupted runs):

```bash
python3 "{baseDir}/scripts/run_state.py" plan "<temp_dir>"
```

Capture stdout JSON:
- `pending_chunk_ids` — Chunks to proofread and fact-check in this run.
- `record_only_chunk_ids` — Chunks that already have valid `issues_chunkNNNN.json` files but need state recording.
- `completed_chunk_ids` — Chunks already recorded and up-to-date.

If `record_only_chunk_ids` is non-empty, record them first:

```bash
python3 "{baseDir}/scripts/run_state.py" record "<temp_dir>" chunk0001 chunk0002 ...
```

Use `pending_chunk_ids` as the work queue for Step 5. If it is empty, skip to Step 6.

---

### 5. Parallel Proofreading & Fact-Checking with Sub-Agents

Process `pending_chunk_ids` in batches (up to `concurrency` sub-agents in parallel; wait for each batch to finish before starting the next).
Depending on total chunk count, you may assign **1 to 3 chunks per sub-agent**.

**Platform-neutral execution**:
- **Claude Code**: Use the `Agent` / `Task` tool to launch parallel sub-agents.
- **Antigravity**: Use `invoke_subagent` (`TypeName: "self"`).
- **OpenClaw**: Use `sessions_spawn` or equivalent sub-agent tool.
- **Codex / Single-agent runtimes**: If your runtime provides sub-agent spawning, use it; otherwise process the chunks sequentially in batches using your file and web-search tools.

Each worker/sub-agent needs:
- File read/write access (`Read`/`Write` or `read_file`/`write_file`) to read `chunkNNNN.md` and write `issues_chunkNNNN.json`.
- Web search access (`WebSearch`/`WebFetch`, `search_web`, or equivalent web lookup tool) to verify factual claims.

#### Neighbor Context Assembly (Optional)
Before inspecting `chunkNNNN.md`, run (or instruct the sub-agent to run):
```bash
python3 "{baseDir}/scripts/chunk_context.py" "<temp_dir>" "chunk<NNNN>.md"
```
This prints ~300 characters from the end of the previous chunk and the start of the next chunk so sentences or entity contexts split across chunk boundaries are understood accurately.

#### Sub-Agent Prompt Template

Pass the following instructions to each sub-agent:

```markdown
당신은 한국어 출판 교정·교열 전문가이자 팩트체커입니다.
할당된 청크 파일: `<temp_dir>/chunk<NNNN>.md`
결과 저장 경로: `<temp_dir>/issues_chunk<NNNN>.json`

### 작업 절차
1. `<temp_dir>/chunk<NNNN>.md` 파일을 읽습니다. 본문에는 `<!-- PAGE: N -->` 형태의 페이지 마커가 포함되어 있습니다. 각 문장이 몇 페이지(`page`)에 속하는지 정확히 추적하세요.
2. **한글 맞춤법·띄어쓰기·어법 검사 (`category: "spelling"`)**:
   - 국립국어원 어문 규범(한글 맞춤법, 표준어 규정, 외래어 표기법, 문장부호)을 기준으로 오탈자, 잘못된 띄어쓰기, 호응 오류, 명백한 비문, 잘못된 조사/어미 결합을 찾습니다.
   - 단, 소설/에세이 등의 의도된 구어체 대화문, 방언, 시적 허용은 문맥을 고려하여 명백한 오류이거나 독해를 해치는 경우에만 지적하세요.
   - PDF 줄바꿈으로 인해 단어 중간에 공백이 들어간 단순 추출 아티팩트는 실제 원문 오류가 아니므로 무시하세요.
3. **팩트체크 (`category: "fact_check"`)**:
   - 본문에 등장하는 역사적 연도·사건, 실존 인물·지명·기관명, 과학/의학/법률/경제적 사실, 통계 수치, 인용문, 상식적 모순 등 검증 가능한 사실 관계를 식별합니다.
   - **반드시 웹 검색 도구(`WebSearch`, `search_web` 등 런타임 제공 검색 도구)를 사용하여 교차 검증**하세요.
   - 사실과 다르거나, 연도/수치/명칭에 오류가 있거나, 문맥상 전후 설정/사실 관계가 충돌하여 검토가 필요한 항목을 기록합니다.
4. **결과 JSON 작성 (`<temp_dir>/issues_chunk<NNNN>.json`)**:
   - 반드시 아래 JSON 스키마에 맞춰 저장하세요 (이슈가 하나도 없더라도 빈 배열 `"issues": []`로 파일을 생성해야 합니다):

```json
{
  "schema_version": 1,
  "chunk_id": "chunk<NNNN>",
  "issues": [
    {
      "page": 6,
      "category": "spelling",
      "subcategory": "맞춤법/띄어쓰기",
      "severity": "error",
      "exact_quote": "안되요",
      "context_quote": "그렇게 하면 안되요 라고 말했다.",
      "suggestion": "안 돼요",
      "explanation": "'안 되다'에 어미 '-어요'가 결합한 형태이므로 '안 돼요'로 적어야 하며, 부사 '안'은 뒷말과 띄어 씁니다.",
      "sources": []
    },
    {
      "page": 12,
      "category": "fact_check",
      "subcategory": "역사/연도 오류",
      "severity": "warning",
      "exact_quote": "1989년 베를린 장벽이 건설되면서",
      "context_quote": "1989년 베를린 장벽이 건설되면서 냉전이 심화되었다.",
      "suggestion": "1961년 베를린 장벽이 건설 (또는 1989년 베를린 장벽이 붕괴)",
      "explanation": "베를린 장벽은 1961년 8월에 건설되었으며, 1989년 11월은 장벽이 붕괴된 해입니다.",
      "sources": ["https://ko.wikipedia.org/wiki/베를린_장벽"]
    }
  ]
}
```

### 중요 규칙 (`exact_quote` 작성법)
- `exact_quote`는 PDF 원문 페이지에서 텍스트 좌표를 찾아 하이라이트와 노트를 찍는 데 사용됩니다.
- 반드시 해당 페이지(`<!-- PAGE: N -->`)에 실제로 존재하는 **고유한 짧은 구절(3~25자 내외)**을 원문 글자 그대로(`exact_quote`) 기입하세요.
- `context_quote`에는 주변 문장 전체를 넣어 동음이의어나 중복 출현 시 정확한 위치를 특정할 수 있게 하세요.
```

#### After Each Batch Completes:
Record completed chunks in `run_state.json`:
```bash
python3 "{baseDir}/scripts/run_state.py" record "<temp_dir>" chunk0001 chunk0002 ...
```

---

### 6. Verify Completeness and Annotate the PDF

After all batches finish, check status via:

```bash
python3 "{baseDir}/scripts/run_state.py" status "<temp_dir>"
```

Retry any missing chunks (up to 1 retry). Once all chunks have valid `issues_chunkNNNN.json` files, merge all findings and inject PDF annotations (Highlight + Sticky Notes) directly into the PDF document:

```bash
uv run --with pymupdf python3 "{baseDir}/scripts/annotate_pdf.py" \
  --pdf "<pdf_path>" \
  --temp-dir "<temp_dir>" \
  --output-pdf "<output_pdf>" \
  --report-md "<report_md_path>"
```
*(Fallback if `uv` is unavailable: `python3 "{baseDir}/scripts/annotate_pdf.py" ...`)*

- **In-place annotation on the original PDF**: If the user wants the notes added directly onto the original PDF file path, pass `--in-place`. `annotate_pdf.py --in-place` creates a backup (`{filename}.orig.pdf`) and updates `<pdf_path>` directly with the annotations, while also saving `{filename}_checked.pdf` if requested.
- **How PDF Annotations Work**:
  - **Spelling / Grammar (`category: "spelling"`)**: Highlighted in **Yellow/Amber** (`#FFD926`) + Sticky Note popup containing `[맞춤법/교열]`, 원문, 수정 제안, 설명.
  - **Fact-Check (`category: "fact_check"`)**: Highlighted in **Coral/Red** (`#FF7359`) + Sticky Note icon (`Help`/`Note`) containing `[팩트체크 검토]`, 원문, 수정 제안, 검토 의견, 참고 출처 URL.
  - **Line-Wrap Resilient Matching**: Even if a phrase in the PDF wraps across two lines (e.g., `들렸\n다`), `annotate_pdf.py` uses character-level bounding box mapping (ignoring whitespace/newlines) to highlight the exact characters across lines and attach the popup note accurately. If a phrase cannot be matched to character coordinates, a fallback sticky note is placed in the top-right margin of that page so no finding is ever lost.

---

### 7. Report Results

Present a clear summary to the user:
1. **Annotated PDF file path** and **Markdown Report path**
2. **Total pages & chunks inspected**
3. **Summary statistics**:
   - Total issues found (맞춤법/띄어쓰기/문법 N건, 팩트체크 검토 N건)
   - Exact highlight match count vs. page-margin fallback note count
4. **Key highlights**: Show a brief table or bullet list of the most important fact-check findings and recurring spelling/style issues.
