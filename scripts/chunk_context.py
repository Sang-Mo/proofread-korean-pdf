#!/usr/bin/env python3
"""
chunk_context.py - Emit neighboring chunk excerpts (~300 characters before and after)
so a proofreading/fact-checking sub-agent has sentence & entity context at chunk boundaries.
"""

import os
import re
import sys


def read_clean_excerpt(filepath, from_end=False, max_chars=300):
    if not os.path.exists(filepath):
        return ""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            text = f.read().strip()
        if not text:
            return ""
        if from_end:
            return text[-max_chars:].strip()
        return text[:max_chars].strip()
    except OSError:
        return ""


def main():
    if len(sys.argv) < 3:
        print("Usage: python3 chunk_context.py <temp_dir> <chunkNNNN.md>", file=sys.stderr)
        sys.exit(1)

    temp_dir = sys.argv[1]
    chunk_name = os.path.basename(sys.argv[2])
    m = re.match(r"^chunk(\d{4})\.md$", chunk_name)
    if not m:
        sys.exit(0)

    idx = int(m.group(1))
    prev_path = os.path.join(temp_dir, f"chunk{idx - 1:04d}.md") if idx > 1 else ""
    next_path = os.path.join(temp_dir, f"chunk{idx + 1:04d}.md")

    prev_excerpt = read_clean_excerpt(prev_path, from_end=True) if prev_path else ""
    next_excerpt = read_clean_excerpt(next_path, from_end=False)

    parts = []
    if prev_excerpt:
        parts.append(f"[이전 청크 말미 참고용 (교정/검사 대상 아님)]\n{prev_excerpt}")
    if next_excerpt:
        parts.append(f"[다음 청크 도입부 참고용 (교정/검사 대상 아님)]\n{next_excerpt}")

    if parts:
        print("\n\n".join(parts))


if __name__ == "__main__":
    main()
