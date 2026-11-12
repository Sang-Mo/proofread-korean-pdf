#!/usr/bin/env python3
"""
annotate_pdf.py - Merge all issues_chunkNNNN.json files, verify completeness,
and write Highlight + Sticky Note annotations directly onto the PDF document,
plus generate a clean Markdown summary report.
"""

import os
import sys
import json
import shutil
import argparse
import re

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        print("Error: PyMuPDF is required. Run with: uv run --with pymupdf python3 annotate_pdf.py ...", file=sys.stderr)
        sys.exit(1)


def normalize_quote(s):
    """Normalize quotes and strip whitespace for character-level matching."""
    if not s:
        return ""
    replacements = {
        "“": '"', "”": '"', "‘": "'", "’": "'",
        "…": "...", "―": "-", "–": "-", "—": "-"
    }
    out = []
    for ch in s:
        if ch.isspace():
            continue
        out.append(replacements.get(ch, ch))
    return "".join(out)


def extract_page_char_stream(page):
    """Return a list of (normalized_char, pymupdf.Rect) for all non-whitespace characters on the page."""
    raw = page.get_text("rawdict")
    stream = []
    replacements = {
        "“": '"', "”": '"', "‘": "'", "’": "'",
        "―": "-", "–": "-", "—": "-"
    }
    for b in raw.get("blocks", []):
        if b.get("type") != 0:
            continue
        for line in b.get("lines", []):
            for span in line.get("spans", []):
                for ch_obj in span.get("chars", []):
                    c = ch_obj.get("c", "")
                    if not c or c.isspace():
                        continue
                    bbox = pymupdf.Rect(ch_obj["bbox"])
                    c_norm = replacements.get(c, c)
                    stream.append((c_norm, bbox))
    return stream


def group_char_rects_by_line(rects):
    """Merge adjacent character bounding boxes on the same line into line-level Rects."""
    if not rects:
        return []
    lines = []
    cur = pymupdf.Rect(rects[0])
    for r in rects[1:]:
        # Same line if vertical centers are close (within half height)
        cur_mid_y = (cur.y0 + cur.y1) / 2.0
        r_mid_y = (r.y0 + r.y1) / 2.0
        height = max(cur.height, r.height, 8.0)
        if abs(cur_mid_y - r_mid_y) < height * 0.65:
            cur = cur | pymupdf.Rect(r)
        else:
            lines.append(cur)
            cur = pymupdf.Rect(r)
    lines.append(cur)
    return lines


def find_phrase_rects_on_page(page, exact_quote, context_quote=""):
    """
    Find bounding box Rects for `exact_quote` on `page`.
    Tries:
      1. Direct `page.search_for(exact_quote)`
      2. Whitespace-normalized character stream matching (handles mid-word line wraps like '들렸\\n다')
         disambiguated by `context_quote` if multiple matches exist.
      3. Prefix/substring fallback if exact_quote is slightly altered.
    Returns: list of pymupdf.Rect (empty list if not found).
    """
    if not exact_quote or not exact_quote.strip():
        return []

    q_clean = exact_quote.strip()

    # 1. Try native search_for first
    direct_hits = page.search_for(q_clean)
    if len(direct_hits) == 1:
        return direct_hits

    # 2. Build character stream for line-wrap resilient search
    stream = extract_page_char_stream(page)
    if not stream:
        return direct_hits

    page_str = "".join(ch for ch, _ in stream)
    target_str = normalize_quote(q_clean)
    context_str = normalize_quote(context_quote) if context_quote else ""

    if not target_str:
        return direct_hits

    # Find all occurrences of target_str in page_str
    matches = []
    start = 0
    while True:
        idx = page_str.find(target_str, start)
        if idx == -1:
            break
        matches.append((idx, idx + len(target_str)))
        start = idx + 1

    # If no full match, try matching first 8 chars or last 8 chars if target_str is long
    if not matches and len(target_str) >= 6:
        half = max(4, len(target_str) // 2)
        for sub in (target_str[:half], target_str[-half:]):
            idx = page_str.find(sub)
            if idx != -1:
                matches.append((idx, idx + len(sub)))
                break

    if not matches:
        return direct_hits

    chosen_start, chosen_end = matches[0]
    if len(matches) > 1 and context_str:
        # Disambiguate using context_str
        ctx_idx = page_str.find(context_str)
        if ctx_idx != -1:
            ctx_end = ctx_idx + len(context_str)
            for m_start, m_end in matches:
                if m_start >= ctx_idx - 10 and m_end <= ctx_end + 10:
                    chosen_start, chosen_end = m_start, m_end
                    break

    char_rects = [stream[i][1] for i in range(chosen_start, chosen_end)]
    return group_char_rects_by_line(char_rects)


def locate_across_candidate_pages(doc, primary_page, candidate_pages, exact_quote, context_quote=""):
    """Search primary_page first, then neighboring/chunk pages if not found."""
    total_pages = len(doc)
    search_order = []
    if 1 <= primary_page <= total_pages:
        search_order.append(primary_page)
    for p in candidate_pages:
        if 1 <= p <= total_pages and p not in search_order:
            search_order.append(p)
    # Also check primary_page - 1 and primary_page + 1 just in case
    for delta in (-1, 1):
        p = primary_page + delta
        if 1 <= p <= total_pages and p not in search_order:
            search_order.append(p)

    for pno in search_order:
        page = doc[pno - 1]
        rects = find_phrase_rects_on_page(page, exact_quote, context_quote)
        if rects:
            return pno, rects

    fallback_page = primary_page if 1 <= primary_page <= total_pages else (search_order[0] if search_order else 1)
    return fallback_page, []


def format_annotation_note(issue):
    """Format the popup note content attached to the PDF annotation."""
    cat = issue.get("category", "spelling")
    subcat = issue.get("subcategory", "")
    badge = "[팩트체크 검토]" if cat == "fact_check" else "[맞춤법/교열]"
    if subcat:
        badge += f" ({subcat})"

    exact_q = issue.get("exact_quote", "").strip()
    suggestion = issue.get("suggestion", "").strip()
    explanation = issue.get("explanation", "").strip()
    sources = issue.get("sources") or []

    lines = [badge]
    if exact_q:
        lines.append(f"• 원문: {exact_q}")
    if suggestion:
        lines.append(f"• 제안/수정: {suggestion}")
    if explanation:
        lines.append(f"• 검토 의견: {explanation}")
    if sources:
        lines.append(f"• 참고 자료: {', '.join(str(s) for s in sources[:3])}")

    return "\n".join(lines)


def add_issue_annotation(page, rects, issue, fallback_index=0):
    """Add Highlight + Popup Note (and Sticky Note icon for fact-check or fallback) onto a PDF page."""
    cat = issue.get("category", "spelling")
    is_fact = (cat == "fact_check")
    title = "팩트체크 검토" if is_fact else "한글 맞춤법·교열"
    subject = issue.get("subcategory") or ("팩트체크" if is_fact else "맞춤법/띄어쓰기")
    content = format_annotation_note(issue)

    # Color palette:
    # Spelling/grammar: Warm Yellow/Amber highlight (1.0, 0.85, 0.15)
    # Fact-check: Coral/Orange-Red highlight (1.0, 0.45, 0.35)
    highlight_color = (1.0, 0.45, 0.35) if is_fact else (1.0, 0.85, 0.15)
    note_color = (1.0, 0.35, 0.25) if is_fact else (1.0, 0.78, 0.1)

    if rects:
        try:
            hl = page.add_highlight_annot(rects)
            hl.set_colors(stroke=highlight_color)
            hl.set_info(title=title, subject=subject, content=content)
            hl.update()

            # Also place a small sticky note icon right at the end of the first highlight rect
            # so readers using PDF viewers that only show icons for Text annotations immediately see the note marker
            r0 = rects[0]
            note_pt = pymupdf.Point(min(page.rect.width - 24, r0.x1 + 3), max(12, r0.y0 - 2))
            t_annot = page.add_text_annot(note_pt, content, icon="Help" if is_fact else "Comment")
            t_annot.set_colors(stroke=note_color)
            t_annot.set_info(title=title, subject=subject, content=content)
            t_annot.update()
            return True
        except Exception:
            pass

    # Fallback: place sticky note in the top-right margin of the page
    y_offset = 28 + (fallback_index * 22) % int(max(200, page.rect.height - 60))
    pt = pymupdf.Point(max(20, page.rect.width - 36), y_offset)
    t_annot = page.add_text_annot(pt, content, icon="Note")
    t_annot.set_colors(stroke=note_color)
    t_annot.set_info(title=title, subject=subject, content=content)
    t_annot.update()
    return False


def generate_markdown_report(report_path, pdf_path, output_pdf_path, total_pages, all_issues, stats):
    """Write a comprehensive Markdown report of all spelling & fact-check findings."""
    spelling_issues = [i for i in all_issues if i.get("category") != "fact_check"]
    fact_issues = [i for i in all_issues if i.get("category") == "fact_check"]

    lines = [
        f"# 한글 맞춤법 및 팩트체크 검수 보고서",
        "",
        f"- **원본 PDF**: `{os.path.basename(pdf_path)}` (총 {total_pages}페이지)",
        f"- **주석(노트) 표시된 PDF**: `{output_pdf_path}`",
        f"- **총 검출 항목**: **{len(all_issues)}건** (맞춤법·띄어쓰기·교열: **{len(spelling_issues)}건**, 팩트체크 검토: **{len(fact_issues)}건**)",
        f"- **PDF 본문 하이라이트+노트 매칭**: {stats['exact_matched']}건 (페이지 여백 노트: {stats['fallback_notes']}건)",
        "",
        "---",
        "",
        "## 1. 팩트체크 검토 항목 (`fact_check`)",
        "",
    ]

    if not fact_issues:
        lines.append("> 검출된 팩트체크 이상 항목이 없습니다.")
        lines.append("")
    else:
        for idx, item in enumerate(fact_issues, 1):
            pno = item.get("resolved_page") or item.get("page", "?")
            sub = item.get("subcategory", "사실 확인")
            quote = item.get("exact_quote", "")
            sugg = item.get("suggestion", "")
            expl = item.get("explanation", "")
            srcs = item.get("sources") or []
            lines.append(f"### {idx}. [p.{pno}] {sub} — `{quote}`")
            if sugg:
                lines.append(f"- **검토/수정 제안**: {sugg}")
            if expl:
                lines.append(f"- **상세 내용**: {expl}")
            if srcs:
                lines.append(f"- **참고 출처**: {', '.join(str(s) for s in srcs)}")
            lines.append("")

    lines.extend([
        "---",
        "",
        "## 2. 한글 맞춤법·띄어쓰기·문법 교열 항목 (`spelling`)",
        "",
    ])

    if not spelling_issues:
        lines.append("> 검출된 맞춤법·띄어쓰기 이상 항목이 없습니다.")
        lines.append("")
    else:
        lines.append("| 번호 | 페이지 | 구분 | 원문 (`exact_quote`) | 수정 제안 (`suggestion`) | 설명 |")
        lines.append("| :---: | :---: | :---: | --- | --- | --- |")
        for idx, item in enumerate(spelling_issues, 1):
            pno = item.get("resolved_page") or item.get("page", "?")
            sub = (item.get("subcategory") or "맞춤법").replace("|", "\\|")
            quote = (item.get("exact_quote") or "").replace("|", "\\|").replace("\n", " ")
            sugg = (item.get("suggestion") or "").replace("|", "\\|").replace("\n", " ")
            expl = (item.get("explanation") or "").replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {idx} | p.{pno} | {sub} | `{quote}` | **{sugg}** | {expl} |")
        lines.append("")

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description="Annotate Korean PDF with proofreading & fact-check sticky notes.")
    parser.add_argument("--pdf", required=True, help="Path to the input PDF file")
    parser.add_argument("--temp-dir", required=True, help="Path to {filename}_proofread_temp directory")
    parser.add_argument("--output-pdf", default=None, help="Path to output annotated PDF (default: {stem}_checked.pdf)")
    parser.add_argument("--in-place", action="store_true", help="Also write annotations directly into the original PDF (creates a .orig.pdf backup)")
    parser.add_argument("--report-md", default=None, help="Path to output Markdown summary report (default: {stem}_proofread_report.md)")
    parser.add_argument("--allow-partial", action="store_true", help="Annotate even if some chunks are missing")

    args = parser.parse_args()
    pdf_path = os.path.abspath(args.pdf)
    temp_dir = os.path.abspath(args.temp_dir)

    if not os.path.exists(pdf_path):
        print(f"Error: PDF not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    manifest_path = os.path.join(temp_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        print(f"Error: manifest.json not found in {temp_dir}", file=sys.stderr)
        sys.exit(1)

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    chunks = sorted(manifest.get("chunks", []), key=lambda c: c["order"])
    missing = []
    all_issues = []

    for c in chunks:
        cid = c["id"]
        issues_path = os.path.join(temp_dir, c["issues_file"])
        if not os.path.exists(issues_path) or os.path.getsize(issues_path) == 0:
            missing.append(cid)
            continue
        try:
            with open(issues_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            chunk_issues = data.get("issues", [])
            for iss in chunk_issues:
                iss["_chunk_id"] = cid
                iss["_chunk_pages"] = c.get("pages", [])
                all_issues.append(iss)
        except Exception as e:
            print(f"Warning: Malformed JSON in {issues_path}: {e}", file=sys.stderr)
            missing.append(cid)

    if missing and not args.allow_partial:
        print(f"Error: Missing or invalid issues files for chunks: {', '.join(missing)}", file=sys.stderr)
        print("Re-run sub-agents for missing chunks or pass --allow-partial.", file=sys.stderr)
        sys.exit(1)

    stem = os.path.splitext(pdf_path)[0]
    output_pdf_path = os.path.abspath(args.output_pdf) if args.output_pdf else f"{stem}_checked.pdf"
    report_md_path = os.path.abspath(args.report_md) if args.report_md else f"{stem}_proofread_report.md"

    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)

    stats = {
        "total_issues": len(all_issues),
        "spelling_count": 0,
        "fact_check_count": 0,
        "exact_matched": 0,
        "fallback_notes": 0,
    }
    fallback_counts_per_page = {}

    # Sort issues by page number
    all_issues.sort(key=lambda x: int(x.get("page") or (x.get("_chunk_pages") or [1])[0]))

    for iss in all_issues:
        cat = iss.get("category", "spelling")
        if cat == "fact_check":
            stats["fact_check_count"] += 1
        else:
            stats["spelling_count"] += 1

        primary_page = int(iss.get("page") or (iss.get("_chunk_pages") or [1])[0])
        candidate_pages = iss.get("_chunk_pages") or [primary_page]
        exact_quote = iss.get("exact_quote", "")
        context_quote = iss.get("context_quote", "")

        resolved_page, rects = locate_across_candidate_pages(
            doc, primary_page, candidate_pages, exact_quote, context_quote
        )
        iss["resolved_page"] = resolved_page
        page_obj = doc[resolved_page - 1]

        fb_idx = fallback_counts_per_page.get(resolved_page, 0)
        matched = add_issue_annotation(page_obj, rects, iss, fallback_index=fb_idx)
        if matched:
            stats["exact_matched"] += 1
        else:
            stats["fallback_notes"] += 1
            fallback_counts_per_page[resolved_page] = fb_idx + 1

    # Save merged issues JSON in temp_dir
    merged_json_path = os.path.join(temp_dir, "all_issues_merged.json")
    with open(merged_json_path, "w", encoding="utf-8") as f:
        json.dump({"stats": stats, "issues": all_issues}, f, indent=2, ensure_ascii=False)

    # Save annotated PDF
    if os.path.abspath(output_pdf_path) == pdf_path or args.in_place:
        backup_path = f"{stem}.orig.pdf"
        if not os.path.exists(backup_path):
            shutil.copy2(pdf_path, backup_path)
            print(f"Backed up original PDF to: {backup_path}")
        tmp_save = f"{stem}.tmp_annot.pdf"
        doc.save(tmp_save, garbage=1, deflate=True)
        doc.close()
        shutil.move(tmp_save, pdf_path)
        if os.path.abspath(output_pdf_path) != pdf_path:
            shutil.copy2(pdf_path, output_pdf_path)
    else:
        doc.save(output_pdf_path, garbage=1, deflate=True)
        doc.close()

    generate_markdown_report(report_md_path, pdf_path, output_pdf_path, total_pages, all_issues, stats)

    print("=== PDF Annotation & Proofreading Report Complete ===")
    print(f"Total issues annotated : {stats['total_issues']} (Spelling/Grammar: {stats['spelling_count']}, Fact-Check: {stats['fact_check_count']})")
    print(f"Exact text highlights  : {stats['exact_matched']} / {stats['total_issues']} (Page margin notes: {stats['fallback_notes']})")
    print(f"Annotated PDF saved to : {output_pdf_path}")
    if args.in_place:
        print(f"Updated original PDF   : {pdf_path}")
    print(f"Markdown report saved  : {report_md_path}")


if __name__ == "__main__":
    main()
