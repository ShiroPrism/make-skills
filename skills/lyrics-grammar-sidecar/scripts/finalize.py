#!/usr/bin/env python3
"""Verify the complete Schema v3 audit chain and atomically write the production sidecar."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sidecarlib import SidecarError, configure_utf8_stdio
from v3lib import finalize_sidecar_v3


def _resolve_workdir_and_output(target: Path, explicit_workdir: Path | None, explicit_output: Path | None) -> tuple[Path, Path]:
    resolved = target.expanduser().resolve()
    if resolved.is_dir() or resolved.name.endswith(".grammar-work"):
        workdir = explicit_workdir.expanduser().resolve() if explicit_workdir else resolved
        stem = workdir.name[:-len(".grammar-work")] if workdir.name.endswith(".grammar-work") else workdir.name
        output = explicit_output.expanduser().resolve() if explicit_output else (workdir.parent / f"{stem}.json")
    elif resolved.suffix.lower() == ".lrc":
        workdir = (
            explicit_workdir.expanduser().resolve()
            if explicit_workdir
            else (resolved.parent / f"{resolved.stem}.grammar-work").resolve()
        )
        output = explicit_output.expanduser().resolve() if explicit_output else resolved.with_suffix(".json")
    else:
        workdir = explicit_workdir.expanduser().resolve() if explicit_workdir else resolved.parent
        stem = workdir.name[:-len(".grammar-work")] if workdir.name.endswith(".grammar-work") else resolved.stem
        output = explicit_output.expanduser().resolve() if explicit_output else (workdir.parent / f"{stem}.json")
    return workdir, output


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=(
            "Require a frozen v3 candidate, passing independent semantic audit, "
            "stage-bound proofs, and an unchanged hash chain before writing <song>.json (single or batch)."
        )
    )
    parser.add_argument(
        "targets",
        type=Path,
        nargs="+",
        help="<song.lrc> or <song>.grammar-work directory (single or batch)",
    )
    parser.add_argument("--workdir", type=Path, help="<song>.grammar-work directory (single target only)")
    parser.add_argument("--output", type=Path, help="Destination <song>.json (single target only)")
    parser.add_argument("--bilingual", type=Path, help="bilingual-lyrics.frozen.json (single target only)")
    parser.add_argument("--draft", type=Path, help="semantic-draft.json (single target only)")
    parser.add_argument("--candidate", type=Path, help="analysis-candidate.json (single target only)")
    parser.add_argument("--candidate-hash", type=Path, help="analysis-candidate.sha256 (single target only)")
    parser.add_argument("--audit", type=Path, help="semantic-audit.json (single target only)")
    parser.add_argument("--grammar-isolation", type=Path, help="Grammar child proof (single target only)")
    parser.add_argument("--audit-isolation", type=Path, help="Audit child proof (single target only)")
    parser.add_argument(
        "--learner-language",
        required=True,
        help="Language for learner-facing prose, e.g. zh-CN.",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Replace an existing differing production JSON.",
    )
    args = parser.parse_args()

    single = len(args.targets) == 1
    if not single and any(
        opt is not None
        for opt in (
            args.workdir,
            args.output,
            args.bilingual,
            args.draft,
            args.candidate,
            args.candidate_hash,
            args.audit,
            args.grammar_isolation,
            args.audit_isolation,
        )
    ):
        print("ERROR: single-target overrides cannot be used with multiple targets.", file=sys.stderr)
        return 2

    fail_count = 0
    for item in args.targets:
        workdir, output_path = _resolve_workdir_and_output(
            item,
            args.workdir if single else None,
            args.output if single else None,
        )
        try:
            output, changed = finalize_sidecar_v3(
                output_path,
                workdir,
                learner_language=args.learner_language,
                frozen_bilingual_path=args.bilingual if single else None,
                draft_path=args.draft if single else None,
                candidate_path=args.candidate if single else None,
                candidate_hash_path=args.candidate_hash if single else None,
                audit_path=args.audit if single else None,
                grammar_proof_path=args.grammar_isolation if single else None,
                audit_proof_path=args.audit_isolation if single else None,
                replace=args.replace,
            )
            action = "written" if changed else "unchanged"
            print(f"{action}: {output}")
            print(f"finalizeReport: {workdir / 'finalize-report.json'}")
        except SidecarError as exc:
            print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
            print(f"finalizeReport: {workdir / 'finalize-report.json'}", file=sys.stderr)
            fail_count += 1
        except Exception as exc:
            print(f"ERROR: failed on {item.name}: {exc}", file=sys.stderr)
            fail_count += 1

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
