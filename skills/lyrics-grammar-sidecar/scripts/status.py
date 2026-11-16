#!/usr/bin/env python3
"""Batch status inspector for lyrics grammar sidecar workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import configure_utf8_stdio


def inspect_song(lrc_file: Path) -> dict:
    lrc_file = lrc_file.resolve()
    stem = lrc_file.stem
    workdir = lrc_file.parent / f"{stem}.grammar-work"
    json_file = lrc_file.parent / f"{stem}.json"

    has_workdir = workdir.is_dir()
    has_proj = (workdir / "source-projection.json").is_file() if has_workdir else False
    has_trans = (workdir / "translated.lrc").is_file() if has_workdir else False
    has_draft = (workdir / "semantic-draft.json").is_file() if has_workdir else False
    has_g_iso = (workdir / "isolation-grammar-analysis.json").is_file() if has_workdir else False
    has_cand = (workdir / "analysis-candidate.json").is_file() if has_workdir else False
    has_audit = (workdir / "semantic-audit.json").is_file() if has_workdir else False
    has_a_iso = (workdir / "isolation-semantic-audit.json").is_file() if has_workdir else False
    has_json = json_file.is_file()

    if not has_proj:
        next_action = "Phase 1: project_source.py"
    elif not has_trans:
        next_action = "Phase 1: Translate & Freeze"
    elif not has_draft:
        next_action = "Phase 2: Grammar Child"
    elif not has_g_iso:
        next_action = "Phase 2: record_isolation.py"
    elif not has_cand:
        next_action = "Phase 2: prepare.py"
    elif not has_audit:
        next_action = "Phase 3: Semantic Auditor"
    elif not has_a_iso:
        next_action = "Phase 3: record_isolation.py"
    elif not has_json:
        next_action = "Phase 4: finalize.py"
    else:
        next_action = "Complete (Valid)"

    return {
        "song": stem,
        "lrc": str(lrc_file),
        "proj": has_proj,
        "trans": has_trans,
        "draft": has_draft,
        "g_iso": has_g_iso,
        "cand": has_cand,
        "audit": has_audit,
        "a_iso": has_a_iso,
        "final": has_json,
        "nextAction": next_action,
    }


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Inspect batch progress and next required action for lyrics grammar sidecars."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=["."],
        help="Directories or .lrc files to inspect (default: current directory)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    args = parser.parse_args()

    lrc_files: list[Path] = []
    for target_str in args.targets:
        target = Path(target_str).expanduser().resolve()
        if target.is_dir():
            lrc_files.extend(sorted(target.glob("*.lrc")))
        elif target.is_file() and target.suffix.lower() == ".lrc":
            lrc_files.append(target)
        else:
            print(f"Warning: skipping non-LRC target: {target}", file=sys.stderr)

    # De-duplicate while preserving order
    seen = set()
    unique_lrcs = []
    for p in lrc_files:
        if p not in seen:
            seen.add(p)
            unique_lrcs.append(p)

    if not unique_lrcs:
        print("No .lrc files found.", file=sys.stderr)
        return 1

    records = [inspect_song(p) for p in unique_lrcs]

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    header = f"{'Song':<40} {'Proj':<5} {'Trans':<5} {'Draft':<5} {'GIso':<5} {'Cand':<5} {'Audit':<5} {'AIso':<5} {'Final':<5} {'Next Action'}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for r in records:
        name = r["song"]
        if len(name) > 38:
            name = name[:35] + "..."
        p = "Y" if r["proj"] else "-"
        t = "Y" if r["trans"] else "-"
        d = "Y" if r["draft"] else "-"
        gi = "Y" if r["g_iso"] else "-"
        c = "Y" if r["cand"] else "-"
        a = "Y" if r["audit"] else "-"
        ai = "Y" if r["a_iso"] else "-"
        f = "Y" if r["final"] else "-"
        print(f"{name:<40} {p:<5} {t:<5} {d:<5} {gi:<5} {c:<5} {a:<5} {ai:<5} {f:<5} {r['nextAction']}")
    print(sep)
    completed = sum(1 for r in records if r["nextAction"] == "Complete (Valid)")
    print(f"Total: {len(records)} songs | Completed: {completed} | In progress: {len(records) - completed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
