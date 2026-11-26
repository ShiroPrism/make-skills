#!/usr/bin/env python3
"""Validate a finalized Schema v3 sidecar and its complete audit chain."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from sidecarlib import (
    SCHEMA_VERSION,
    SidecarError,
    assert_distinct_paths,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    write_json_atomic,
)
from v3lib import validate_finalized_sidecar_v3


def _archive_audit_proofs(workdir_path: Path, archive_root: Path) -> str:
    """Copy isolation proofs, manifest, and audit reports before removing workdir."""
    resolved_workdir = workdir_path.expanduser().resolve()
    stem = (
        resolved_workdir.name[: -len(".grammar-work")]
        if resolved_workdir.name.endswith(".grammar-work")
        else resolved_workdir.name
    )
    dest = archive_root.expanduser().resolve() / stem
    dest.mkdir(parents=True, exist_ok=True)
    for filename in (
        "translation-manifest.json",
        "isolation-grammar-analysis.json",
        "isolation-semantic-audit.json",
        "semantic-audit.json",
        "analysis-candidate.sha256",
        "finalize-report.json",
    ):
        src = resolved_workdir / filename
        if src.is_file():
            shutil.copy2(src, dest / filename)
    history_src = resolved_workdir / "audit-history"
    if history_src.is_dir():
        history_dest = dest / "audit-history"
        if history_dest.exists():
            shutil.rmtree(history_dest)
        shutil.copytree(history_src, history_dest)
    return str(dest)


def _cleanup_workdir_dir(workdir_path: Path, report_path: Path | None = None) -> str | None:
    """Remove a .grammar-work directory after full validation passes."""
    resolved_workdir = workdir_path.expanduser().resolve()
    if not resolved_workdir.name.endswith(".grammar-work") or not resolved_workdir.is_dir():
        return None
    if report_path is not None:
        resolved_report = report_path.expanduser().resolve()
        if resolved_workdir == resolved_report or resolved_workdir in resolved_report.parents:
            return None
    shutil.rmtree(resolved_workdir)
    return str(resolved_workdir)


def validate_single_sidecar(
    sidecar_path: Path,
    workdir_path: Path,
    learner_language: str,
    *,
    bilingual_path: Path | None = None,
    report_path: Path | None = None,
    cleanup_workdir: bool = False,
    archive_proofs: Path | None = None,
) -> tuple[dict, list]:
    raw_sidecar_path = sidecar_path.expanduser()
    if raw_sidecar_path.is_symlink():
        raise SidecarError("unsupported_source", "Symlinked sidecars are not supported.")
    resolved_sidecar = raw_sidecar_path.resolve()
    resolved_workdir = workdir_path.expanduser().resolve()
    resolved_bilingual = (
        bilingual_path.expanduser()
        if bilingual_path is not None
        else (resolved_workdir / "bilingual-lyrics.frozen.json")
    )
    resolved_report = report_path.expanduser() if report_path is not None else None
    assert_distinct_paths(
        ("production sidecar", resolved_sidecar),
        ("frozen bilingual lyrics", resolved_bilingual),
        ("translation manifest", resolved_workdir / "translation-manifest.json"),
        ("semantic draft", resolved_workdir / "semantic-draft.json"),
        ("analysis candidate", resolved_workdir / "analysis-candidate.json"),
        ("candidate hash", resolved_workdir / "analysis-candidate.sha256"),
        ("semantic audit", resolved_workdir / "semantic-audit.json"),
        ("grammar isolation proof", resolved_workdir / "isolation-grammar-analysis.json"),
        ("audit isolation proof", resolved_workdir / "isolation-semantic-audit.json"),
        ("validation report", resolved_report),
    )
    bilingual = load_bilingual_lyrics(resolved_bilingual)
    issues = validate_finalized_sidecar_v3(
        resolved_sidecar,
        resolved_workdir,
        learner_language,
        frozen_bilingual_path=resolved_bilingual,
    )
    report: dict = {
        "ok": not issues,
        "schemaVersion": SCHEMA_VERSION,
        "errors": [issue.as_dict() for issue in issues],
        "contentHash": bilingual["contentHash"],
        "sidecar": resolved_sidecar.name,
    }
    if resolved_report is not None:
        write_json_atomic(resolved_report, report, replace=True)
    if not issues and archive_proofs is not None:
        archived = _archive_audit_proofs(resolved_workdir, archive_proofs)
        report["archivedProofs"] = archived
    if cleanup_workdir and not issues:
        cleaned = _cleanup_workdir_dir(resolved_workdir, resolved_report)
        if cleaned is not None:
            report["cleanedWorkdir"] = cleaned
    return report, issues


def _resolve_batch_target(item: Path) -> tuple[Path, Path]:
    resolved = item.expanduser().resolve()
    if resolved.is_dir() or resolved.name.endswith(".grammar-work"):
        stem = resolved.name[:-len(".grammar-work")] if resolved.name.endswith(".grammar-work") else resolved.name
        return (resolved.parent / f"{stem}.json"), resolved
    if resolved.suffix.lower() == ".lrc":
        return resolved.with_suffix(".json"), (resolved.parent / f"{resolved.stem}.grammar-work")
    return resolved, (resolved.parent / f"{resolved.stem}.grammar-work")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Run the full Schema v3 translation, audit, proof, and sidecar check (single or batch)."
    )
    parser.add_argument(
        "files",
        type=Path,
        nargs="+",
        help="Single mode: <sidecar.json> (or <song.lrc> <sidecar.json>); Batch mode: targets...",
    )
    parser.add_argument("--batch", action="store_true", help="Run batch validation across multiple songs")
    parser.add_argument("--workdir", type=Path, help="<song>.grammar-work directory (single mode)")
    parser.add_argument("--bilingual", type=Path, help="Frozen bilingual-lyrics.frozen.json (single mode)")
    parser.add_argument("--report", type=Path, help="Optional validation report (single mode)")
    parser.add_argument("--learner-language", required=True)
    parser.add_argument(
        "--cleanup-workdir",
        action="store_true",
        help="Delete <song>.grammar-work directory automatically after validation passes",
    )
    parser.add_argument(
        "--archive-proofs",
        type=Path,
        help="Optional directory to archive isolation proofs, semantic-audit.json, and audit-history/ before cleanup",
    )
    args = parser.parse_args()

    if args.batch:
        fail_count = 0
        summary = []
        for item in args.files:
            sidecar_path, workdir = _resolve_batch_target(item)
            try:
                report, issues = validate_single_sidecar(
                    sidecar_path,
                    workdir,
                    args.learner_language,
                    cleanup_workdir=args.cleanup_workdir,
                    archive_proofs=args.archive_proofs,
                )
                summary.append(report)
                status = "PASS" if not issues else "FAIL"
                print(f"[{status}] {sidecar_path.name}")
                if issues:
                    fail_count += 1
            except Exception as exc:
                print(f"[ERROR] {item.name}: {exc}", file=sys.stderr)
                fail_count += 1
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0 if fail_count == 0 else 1

    if len(args.files) == 1:
        item = args.files[0].expanduser().resolve()
        if item.suffix.lower() == ".lrc":
            sidecar_path = item.with_suffix(".json")
            workdir = args.workdir or (item.parent / f"{item.stem}.grammar-work")
        else:
            sidecar_path = item
            workdir = args.workdir or (item.parent / f"{item.stem}.grammar-work")
    elif len(args.files) == 2:
        first, second = args.files
        sidecar_path = second
        workdir = args.workdir or (first.parent / f"{first.stem}.grammar-work")
    else:
        print("ERROR: single mode accepts <sidecar.json> or <song.lrc> <sidecar.json>", file=sys.stderr)
        return 2

    try:
        report, issues = validate_single_sidecar(
            sidecar_path,
            workdir,
            args.learner_language,
            bilingual_path=args.bilingual,
            report_path=args.report,
            cleanup_workdir=args.cleanup_workdir,
            archive_proofs=args.archive_proofs,
        )
    except (SidecarError, FileNotFoundError, json.JSONDecodeError) as exc:
        print(f"ERROR [invalid_sidecar] $: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
