#!/usr/bin/env python3
"""Verify and freeze timestamp-free bilingual-lyrics.json for grammar analysis and audit."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    ensure_inside_workdir,
    read_json,
    sha256_file,
    verify_frozen_bilingual,
    write_accepted_bilingual,
)


def _resolve_target(target: Path, workdir_opt: Path | None) -> tuple[Path, Path]:
    resolved = target.expanduser().resolve()
    if resolved.is_dir() or resolved.name.endswith(".grammar-work"):
        workdir = workdir_opt.expanduser().resolve() if workdir_opt else resolved
        bilingual_path = workdir / "bilingual-lyrics.json"
    elif resolved.suffix.lower() == ".lrc":
        workdir = (
            workdir_opt.expanduser().resolve()
            if workdir_opt
            else (resolved.parent / f"{resolved.stem}.grammar-work").resolve()
        )
        bilingual_path = workdir / "bilingual-lyrics.json"
    else:
        bilingual_path = resolved
        workdir = workdir_opt.expanduser().resolve() if workdir_opt else resolved.parent
    return bilingual_path, workdir


def verify_single_bilingual(
    bilingual_path: Path,
    workdir: Path,
    *,
    verify_frozen: bool = False,
    allow_untranslated: bool = False,
    replace: bool = False,
) -> tuple[dict, list, str]:
    workdir = workdir.expanduser().resolve()
    frozen_path = ensure_inside_workdir(
        workdir / "bilingual-lyrics.frozen.json",
        workdir,
        "frozen bilingual lyrics",
    )
    manifest_path = ensure_inside_workdir(
        workdir / "translation-manifest.json",
        workdir,
        "translation manifest",
    )

    if verify_frozen:
        if not manifest_path.exists():
            raise SidecarError("file_not_found", f"Manifest not found: {manifest_path}")
        manifest = read_json(manifest_path)
        report, _bilingual, issues = verify_frozen_bilingual(frozen_path, manifest)
        actual_sha = report.get("bilingualSha256") or sha256_file(frozen_path)
        return report, issues, actual_sha

    frozen_path, manifest, issues = write_accepted_bilingual(
        bilingual_path,
        workdir,
        allow_untranslated=allow_untranslated,
        replace=replace,
    )
    report = dict(manifest)
    report["ok"] = not issues
    return report, issues, manifest.get("bilingualSha256", "")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Verify and freeze timestamp-free bilingual-lyrics.json into bilingual-lyrics.frozen.json + translation-manifest.json."
    )
    parser.add_argument(
        "targets",
        type=Path,
        nargs="+",
        help="Single or batch targets: <workdir>, <bilingual-lyrics.json>, or <song.lrc>",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="<song>.grammar-work directory (single mode only)",
    )
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Verify and freeze multiple targets in batch mode",
    )
    parser.add_argument(
        "--verify-frozen",
        action="store_true",
        help="Verify existing bilingual-lyrics.frozen.json against translation-manifest.json",
    )
    parser.add_argument(
        "--allow-untranslated",
        action="store_true",
        help="Allow bilingual files with zero translated lines (e.g. instrumental/vocalise)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing frozen bilingual snapshot and manifest",
    )
    args = parser.parse_args()

    if len(args.targets) > 1 and args.workdir is not None:
        print("ERROR: --workdir cannot be used with multiple targets.", file=sys.stderr)
        return 2

    if args.batch or len(args.targets) > 1:
        fail_count = 0
        for item in args.targets:
            bilingual_path, workdir = _resolve_target(item, None)
            try:
                report, issues, actual_sha = verify_single_bilingual(
                    bilingual_path,
                    workdir,
                    verify_frozen=args.verify_frozen,
                    allow_untranslated=args.allow_untranslated,
                    replace=args.replace,
                )
                if issues:
                    print(f"FAILED: {item.name}: {[i.code for i in issues]}", file=sys.stderr)
                    fail_count += 1
                else:
                    print(f"FROZEN: {workdir.name} -> {workdir / 'bilingual-lyrics.frozen.json'} ({actual_sha[:16]}...)")
            except SidecarError as exc:
                print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
                fail_count += 1
            except Exception as exc:
                print(f"ERROR: {item.name}: {exc}", file=sys.stderr)
                fail_count += 1
        return 0 if fail_count == 0 else 1

    bilingual_path, workdir = _resolve_target(args.targets[0], args.workdir)
    try:
        report, issues, _sha = verify_single_bilingual(
            bilingual_path,
            workdir,
            verify_frozen=args.verify_frozen,
            allow_untranslated=args.allow_untranslated,
            replace=args.replace,
        )
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 2
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR [invalid_manifest] $: {exc}", file=sys.stderr)
        return 2

    if issues:
        print(
            json.dumps(
                {"ok": False, "errors": [issue.as_dict() for issue in issues]},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 1

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
