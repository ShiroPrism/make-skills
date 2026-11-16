#!/usr/bin/env python3
"""Batch status inspector for lyrics grammar sidecar workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    load_projection,
    read_json,
    verify_source_matches_projection,
)
from v2lib import validate_grammar_analysis_v2


def validate_final_sidecar(
    lrc_file: Path,
    json_file: Path,
    projection_path: Path,
) -> tuple[bool, str | None]:
    try:
        projection = load_projection(projection_path)
        _, source_issues = verify_source_matches_projection(projection, lrc_file)
        if source_issues:
            return False, source_issues[0].code
        document = read_json(json_file)
        learner_language = None
        extensions = document.get("extensions")
        if isinstance(extensions, dict) and isinstance(
            extensions.get("learnerLanguage"), str
        ):
            learner_language = extensions["learnerLanguage"]
        issues = validate_grammar_analysis_v2(
            document,
            projection=projection,
            expected_lrc_file=projection.get("lrcFile"),
            require_projection=True,
            learner_language=learner_language,
        )
    except (SidecarError, OSError, ValueError) as exc:
        code = getattr(exc, "code", "validation_error")
        return False, code
    return (not issues, issues[0].code if issues else None)


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

    final_valid: bool | None = None
    validation_code: str | None = None
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
        final_valid, validation_code = validate_final_sidecar(
            lrc_file,
            json_file,
            workdir / "source-projection.json",
        )
        next_action = (
            "Complete (Valid)"
            if final_valid
            else f"Review: {validation_code or 'validation_error'}"
        )

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
        "finalValid": final_valid,
        "validationCode": validation_code,
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
