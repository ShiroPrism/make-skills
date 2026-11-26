#!/usr/bin/env python3
"""Batch status inspector for Schema v3 lyrics grammar sidecar workflow."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    read_json,
)
from v3lib import validate_grammar_analysis_v3


def validate_final_sidecar(
    json_file: Path,
    bilingual_path: Path | None,
) -> tuple[bool, str | None]:
    try:
        bilingual = (
            load_bilingual_lyrics(bilingual_path)
            if (bilingual_path is not None and bilingual_path.is_file())
            else None
        )
        document = read_json(json_file)
        learner_language = None
        extensions = document.get("extensions")
        if isinstance(extensions, dict) and isinstance(
            extensions.get("learnerLanguage"), str
        ):
            learner_language = extensions["learnerLanguage"]
        issues = validate_grammar_analysis_v3(
            document,
            bilingual=bilingual,
            require_bilingual=bilingual is not None,
            learner_language=learner_language,
        )
    except (SidecarError, OSError, ValueError) as exc:
        code = getattr(exc, "code", "validation_error")
        return False, code
    return (not issues, issues[0].code if issues else None)


def inspect_song(stem: str, base_dir: Path, lrc_file: Path | None = None) -> dict:
    workdir = base_dir / f"{stem}.grammar-work"
    json_file = base_dir / f"{stem}.json"

    has_workdir = workdir.is_dir()
    has_bilingual = (workdir / "bilingual-lyrics.json").is_file() if has_workdir else False
    has_frozen = (workdir / "bilingual-lyrics.frozen.json").is_file() if has_workdir else False
    has_draft = (workdir / "semantic-draft.json").is_file() if has_workdir else False
    has_g_iso = (workdir / "isolation-grammar-analysis.json").is_file() if has_workdir else False
    has_cand = (workdir / "analysis-candidate.json").is_file() if has_workdir else False
    has_audit = (workdir / "semantic-audit.json").is_file() if has_workdir else False
    has_a_iso = (workdir / "isolation-semantic-audit.json").is_file() if has_workdir else False
    has_json = json_file.is_file()

    final_valid: bool | None = None
    validation_code: str | None = None
    if has_json:
        frozen = workdir / "bilingual-lyrics.frozen.json"
        final_valid, validation_code = validate_final_sidecar(
            json_file,
            frozen if frozen.is_file() else None,
        )
        next_action = (
            "Complete (Valid)"
            if final_valid
            else f"Review: {validation_code or 'validation_error'}"
        )
    elif not has_bilingual and not has_frozen:
        next_action = "Phase 1: extract_bilingual.py"
    elif not has_frozen:
        next_action = "Phase 1: verify_translation.py"
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
    else:
        next_action = "Phase 4: finalize.py"

    return {
        "song": stem,
        "lrc": str(lrc_file) if lrc_file else None,
        "bilingual": has_bilingual,
        "frozen": has_frozen,
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
        description="Inspect batch progress and next required action for Schema v3 lyrics grammar sidecars."
    )
    parser.add_argument(
        "targets",
        nargs="*",
        default=["."],
        help="Directories, .lrc files, or .grammar-work directories to inspect (default: current directory)",
    )
    parser.add_argument("--json", action="store_true", help="Output JSON instead of table")
    args = parser.parse_args()

    items: dict[tuple[Path, str], Path | None] = {}
    for target_str in args.targets:
        target = Path(target_str).expanduser().resolve()
        if target.is_dir() and target.name.endswith(".grammar-work"):
            stem = target.name[:-len(".grammar-work")]
            items.setdefault((target.parent, stem), None)
        elif target.is_dir():
            for lrc in sorted(target.glob("*.lrc")):
                items.setdefault((lrc.parent, lrc.stem), lrc)
            for wd in sorted(target.glob("*.grammar-work")):
                if wd.is_dir():
                    stem = wd.name[:-len(".grammar-work")]
                    items.setdefault((wd.parent, stem), None)
        elif target.is_file() and target.suffix.lower() == ".lrc":
            items.setdefault((target.parent, target.stem), target)
        elif target.is_file() and target.suffix.lower() == ".json":
            items.setdefault((target.parent, target.stem), None)
        else:
            print(f"Warning: skipping unsupported target: {target}", file=sys.stderr)

    if not items:
        print("No songs or workdirs found.", file=sys.stderr)
        return 1

    records = [
        inspect_song(stem, base_dir, lrc)
        for (base_dir, stem), lrc in items.items()
    ]

    if args.json:
        print(json.dumps(records, ensure_ascii=False, indent=2))
        return 0

    header = f"{'Song':<38} {'Bil':<4} {'Frz':<4} {'Drf':<4} {'GIso':<5} {'Cnd':<4} {'Aud':<4} {'AIso':<5} {'Fin':<4} {'Next Action'}"
    sep = "-" * len(header)
    print(header)
    print(sep)
    for r in records:
        name = r["song"]
        if len(name) > 36:
            name = name[:33] + "..."
        b = "Y" if r["bilingual"] else "-"
        fr = "Y" if r["frozen"] else "-"
        d = "Y" if r["draft"] else "-"
        gi = "Y" if r["g_iso"] else "-"
        c = "Y" if r["cand"] else "-"
        a = "Y" if r["audit"] else "-"
        ai = "Y" if r["a_iso"] else "-"
        f = "Y" if r["final"] else "-"
        print(f"{name:<38} {b:<4} {fr:<4} {d:<4} {gi:<5} {c:<4} {a:<4} {ai:<5} {f:<4} {r['nextAction']}")
    print(sep)
    completed = sum(1 for r in records if r["nextAction"] == "Complete (Valid)")
    print(f"Total: {len(records)} songs | Completed: {completed} | In progress: {len(records) - completed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
