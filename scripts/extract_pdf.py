#!/usr/bin/env python3
"""
extract_pdf.py - Extract Korean PDF pages into page-tracked Markdown chunks for proofreading and fact-checking.
Preserves <!-- PAGE: N --> markers and reconstructs line-wrapped Korean sentences cleanly while keeping page provenance.
"""

import os
import sys
import glob
import json
import hashlib
import argparse
import re

try:
    import pymupdf
except ImportError:
    try:
        import fitz as pymupdf
    except ImportError:
        print("Error: PyMuPDF is required. Run with: uv run --with pymupdf python3 extract_pdf.py ...", file=sys.stderr)
        sys.exit(1)


def file_hash(filepath):
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def clean_page_blocks(page, page_num):
    """Extract text blocks from a PDF page and clean mid-sentence line wraps while preserving paragraph structure."""
    blocks = page.get_text("blocks", sort=True)
    page_height = page.rect.height
    paragraphs = []

    for b in blocks:
        # b is (x0, y0, x1, y1, text, block_no, block_type)
        if len(b) >= 7 and b[6] != 0:
            continue  # Skip non-text blocks
        x0, y0, x1, y1, raw_text = b[0], b[1], b[2], b[3], b[4]
        text = raw_text.strip()
        if not text:
            continue

        # Skip standalone page numbers near top header or bottom footer
        if re.fullmatch(r"[-–—\s]*\d+[-–—\s]*", text) and (y0 > page_height * 0.88 or y1 < page_height * 0.12):
            continue

        # Process lines inside a block
        lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
        if not lines:
            continue

        merged_lines = []
        for line in lines:
            if not merged_lines:
                merged_lines.append(line)
                continue

            prev = merged_lines[-1]
            # If previous line ended without trailing space in raw block or looks like mid-word/mid-sentence wrap:
            # In PyMuPDF, if a line had a trailing space before '\n', it usually means word boundary wrap;
            # if it had NO trailing space before '\n' (e.g. '들렸\n다.'), it's a mid-ecjeol wrap!
            if not prev.endswith(" ") and not prev.endswith((".", "!", "?", "”", "’", "\"", "'", ":", ";", ")")):
                merged_lines[-1] = prev + line.lstrip()
            else:
                merged_lines[-1] = prev.rstrip() + " " + line.lstrip()

        para_text = "\n".join(merged_lines).strip()
        if para_text:
            paragraphs.append(para_text)

    body = "\n\n".join(paragraphs)
    return f"<!-- PAGE: {page_num} -->\n{body}\n"


def split_pages_into_chunks(page_records, target_size=5000):
    """Group page markdown records into chunks of ~target_size characters without breaking a page unless oversized."""
    chunks = []
    current_pages = []
    current_texts = []
    current_size = 0

    def flush():
        nonlocal current_pages, current_texts, current_size
        if not current_texts:
            return
        chunks.append({
            "pages": list(current_pages),
            "text": "\n\n".join(current_texts).strip() + "\n"
        })
        current_pages = []
        current_texts = []
        current_size = 0

    for rec in page_records:
        pno = rec["page"]
        ptext = rec["text"]
        plen = len(ptext)

        if not ptext.strip() or ptext.strip() == f"<!-- PAGE: {pno} -->":
            continue

        # If a single page is much larger than target_size * 1.8, split by paragraphs while keeping <!-- PAGE: N -->
        if plen > target_size * 1.8:
            flush()
            paras = ptext.split("\n\n")
            header = f"<!-- PAGE: {pno} -->"
            sub_paras = []
            sub_len = 0
            for para in paras:
                if para.startswith("<!-- PAGE:"):
                    continue
                if sub_len + len(para) > target_size and sub_paras:
                    chunks.append({
                        "pages": [pno],
                        "text": header + "\n" + "\n\n".join(sub_paras).strip() + "\n"
                    })
                    sub_paras = [para]
                    sub_len = len(para)
                else:
                    sub_paras.append(para)
                    sub_len += len(para)
            if sub_paras:
                chunks.append({
                    "pages": [pno],
                    "text": header + "\n" + "\n\n".join(sub_paras).strip() + "\n"
                })
            continue

        if current_size + plen > target_size and current_texts:
            flush()

        current_pages.append(pno)
        current_texts.append(ptext.strip())
        current_size += plen

    flush()
    return chunks


def main():
    parser = argparse.ArgumentParser(description="Extract Korean PDF to page-tracked Markdown chunks for proofreading.")
    parser.add_argument("pdf_path", help="Input PDF file path")
    parser.add_argument("--chunk-size", type=int, default=5000, help="Target chunk size in characters (default: 5000)")
    parser.add_argument("--temp-root", default=None, help="Directory under which {filename}_proofread_temp/ is created")
    parser.add_argument("--force", action="store_true", help="Force re-extraction even if cached chunks exist")

    args = parser.parse_args()
    pdf_path = os.path.abspath(args.pdf_path)

    if not os.path.exists(pdf_path):
        print(f"Error: PDF file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    stem = os.path.splitext(os.path.basename(pdf_path))[0]
    temp_leaf = f"{stem}_proofread_temp"
    temp_dir = os.path.join(args.temp_root, temp_leaf) if args.temp_root else os.path.abspath(temp_leaf)
    os.makedirs(temp_dir, exist_ok=True)

    current_fp = {
        "path": pdf_path,
        "size": os.path.getsize(pdf_path),
        "sha256": file_hash(pdf_path),
    }

    fp_path = os.path.join(temp_dir, "source_fingerprint.json")
    manifest_path = os.path.join(temp_dir, "manifest.json")

    if os.path.exists(fp_path) and os.path.exists(manifest_path) and not args.force:
        try:
            with open(fp_path, "r", encoding="utf-8") as f:
                saved_fp = json.load(f)
            if saved_fp.get("sha256") == current_fp["sha256"]:
                with open(manifest_path, "r", encoding="utf-8") as f:
                    manifest = json.load(f)
                print(f"Reusing existing extraction in {temp_dir} ({manifest.get('chunk_count', 0)} chunks).")
                return
            else:
                print("Error: Source PDF SHA-256 differs from existing temp directory. Use --force or delete temp dir.", file=sys.stderr)
                sys.exit(1)
        except Exception as e:
            print(f"Warning: Could not read cached fingerprint ({e}), re-extracting...")

    print(f"=== Extracting PDF for Proofreading & Fact-Checking ===")
    print(f"Input PDF: {pdf_path}")
    doc = pymupdf.open(pdf_path)
    total_pages = len(doc)
    print(f"Total pages: {total_pages}")

    page_records = []
    for idx in range(total_pages):
        page_num = idx + 1
        page_md = clean_page_blocks(doc[idx], page_num)
        page_records.append({
            "page": page_num,
            "text": page_md,
        })

    full_md = "\n\n".join(r["text"].strip() for r in page_records if r["text"].strip()) + "\n"
    input_md_path = os.path.join(temp_dir, "input.md")
    with open(input_md_path, "w", encoding="utf-8") as f:
        f.write(full_md)

    # Remove old source chunk files if re-extracting
    for old_chunk in glob.glob(os.path.join(temp_dir, "chunk*.md")):
        try:
            os.remove(old_chunk)
        except OSError:
            pass

    chunk_items = split_pages_into_chunks(page_records, target_size=args.chunk_size)
    manifest_chunks = []

    for order, item in enumerate(chunk_items, 1):
        chunk_id = f"chunk{order:04d}"
        source_file = f"{chunk_id}.md"
        issues_file = f"issues_{chunk_id}.json"
        chunk_path = os.path.join(temp_dir, source_file)

        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write(item["text"])

        manifest_chunks.append({
            "id": chunk_id,
            "order": order,
            "pages": item["pages"],
            "page_start": min(item["pages"]) if item["pages"] else 1,
            "page_end": max(item["pages"]) if item["pages"] else 1,
            "char_count": len(item["text"]),
            "source_file": source_file,
            "source_hash": file_hash(chunk_path),
            "issues_file": issues_file,
        })

    manifest = {
        "pdf_path": pdf_path,
        "total_pages": total_pages,
        "chunk_count": len(manifest_chunks),
        "target_chunk_size": args.chunk_size,
        "source_hash": file_hash(input_md_path),
        "chunks": manifest_chunks,
    }

    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    with open(fp_path, "w", encoding="utf-8") as f:
        json.dump(current_fp, f, indent=2, ensure_ascii=False)

    config_path = os.path.join(temp_dir, "config.txt")
    with open(config_path, "w", encoding="utf-8") as f:
        f.write(
            f"# Korean PDF Proofreading Configuration\n"
            f"pdf_path={pdf_path}\n"
            f"total_pages={total_pages}\n"
            f"chunk_count={len(manifest_chunks)}\n"
            f"chunk_size={args.chunk_size}\n"
        )

    print(f"Created {len(manifest_chunks)} chunks in: {temp_dir}")
    for c in manifest_chunks:
        p_range = f"p.{c['page_start']}-{c['page_end']}" if c["page_start"] != c["page_end"] else f"p.{c['page_start']}"
        print(f"  {c['id']}: {p_range} ({c['char_count']} chars)")


if __name__ == "__main__":
    main()
