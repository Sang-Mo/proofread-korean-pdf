#!/usr/bin/env python3
"""
run_state.py - Track and plan selective proofreading across chunks (modeled on translate-book/scripts/run_state.py).
Commands:
  plan <temp_dir> [--recheck-all]
  record <temp_dir> chunk0001 [chunk0002 ...]
  status <temp_dir>
"""

import os
import sys
import json
import hashlib
import argparse


def file_hash(filepath):
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def validate_issues_file(path):
    """Verify that issues_chunkNNNN.json exists and is valid JSON with an 'issues' list."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return False, "missing or empty file"
    data = load_json(path)
    if not isinstance(data, dict):
        return False, "not a JSON object"
    if "issues" not in data or not isinstance(data["issues"], list):
        return False, "missing 'issues' array"
    return True, f"{len(data['issues'])} issues"


def cmd_plan(temp_dir, recheck_all=False):
    manifest = load_json(os.path.join(temp_dir, "manifest.json"))
    if not manifest:
        print(json.dumps({"error": "manifest.json not found"}))
        sys.exit(1)

    state_path = os.path.join(temp_dir, "run_state.json")
    state = load_json(state_path, default={"version": 1, "chunks": {}})
    recorded = state.get("chunks", {})

    pending_chunk_ids = []
    record_only_chunk_ids = []
    completed_chunk_ids = []

    for c in sorted(manifest.get("chunks", []), key=lambda x: x["order"]):
        cid = c["id"]
        src_path = os.path.join(temp_dir, c["source_file"])
        issues_path = os.path.join(temp_dir, c["issues_file"])

        if recheck_all or not os.path.exists(src_path):
            pending_chunk_ids.append(cid)
            continue

        valid, _ = validate_issues_file(issues_path)
        if not valid:
            pending_chunk_ids.append(cid)
            continue

        src_hash = file_hash(src_path)
        rec = recorded.get(cid)
        if rec and rec.get("source_hash") == src_hash:
            completed_chunk_ids.append(cid)
        else:
            record_only_chunk_ids.append(cid)

    result = {
        "pending_chunk_ids": pending_chunk_ids,
        "record_only_chunk_ids": record_only_chunk_ids,
        "completed_chunk_ids": completed_chunk_ids,
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_record(temp_dir, chunk_ids):
    manifest = load_json(os.path.join(temp_dir, "manifest.json"))
    if not manifest:
        print("Error: manifest.json not found", file=sys.stderr)
        sys.exit(1)

    chunk_map = {c["id"]: c for c in manifest.get("chunks", [])}
    state_path = os.path.join(temp_dir, "run_state.json")
    state = load_json(state_path, default={"version": 1, "chunks": {}})
    if "chunks" not in state:
        state["chunks"] = {}

    errors = []
    for cid in chunk_ids:
        if cid not in chunk_map:
            errors.append(f"Unknown chunk id: {cid}")
            continue
        c = chunk_map[cid]
        src_path = os.path.join(temp_dir, c["source_file"])
        issues_path = os.path.join(temp_dir, c["issues_file"])

        valid, msg = validate_issues_file(issues_path)
        if not valid:
            errors.append(f"{cid}: invalid output ({msg})")
            continue

        issues_data = load_json(issues_path, default={})
        state["chunks"][cid] = {
            "source_hash": file_hash(src_path) if os.path.exists(src_path) else "",
            "issues_hash": file_hash(issues_path),
            "issue_count": len(issues_data.get("issues", [])),
        }

    if errors:
        for e in errors:
            print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    with open(state_path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)

    print(json.dumps({"recorded": chunk_ids, "total_recorded": len(state["chunks"])}, ensure_ascii=False))


def cmd_status(temp_dir):
    manifest = load_json(os.path.join(temp_dir, "manifest.json"), default={})
    state = load_json(os.path.join(temp_dir, "run_state.json"), default={"chunks": {}})
    chunks = manifest.get("chunks", [])

    valid_count = 0
    total_issues = 0
    missing_chunks = []

    for c in chunks:
        cid = c["id"]
        issues_path = os.path.join(temp_dir, c["issues_file"])
        valid, _ = validate_issues_file(issues_path)
        if valid:
            valid_count += 1
            data = load_json(issues_path, default={})
            total_issues += len(data.get("issues", []))
        else:
            missing_chunks.append(cid)

    summary = {
        "total_chunks": len(chunks),
        "completed_chunks": valid_count,
        "recorded_in_state": len(state.get("chunks", {})),
        "total_issues_found": total_issues,
        "missing_chunk_ids": missing_chunks,
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description="Manage selective proofreading run state.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_plan = sub.add_parser("plan")
    p_plan.add_argument("temp_dir")
    p_plan.add_argument("--recheck-all", action="store_true")

    p_rec = sub.add_parser("record")
    p_rec.add_argument("temp_dir")
    p_rec.add_argument("chunk_ids", nargs="+")

    p_stat = sub.add_parser("status")
    p_stat.add_argument("temp_dir")

    args = parser.parse_args()
    if args.cmd == "plan":
        cmd_plan(args.temp_dir, recheck_all=args.recheck_all)
    elif args.cmd == "record":
        cmd_record(args.temp_dir, args.chunk_ids)
    elif args.cmd == "status":
        cmd_status(args.temp_dir)


if __name__ == "__main__":
    main()
