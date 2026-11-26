#!/usr/bin/env python3
"""Freeze a Schema v3 semantic draft into a normalized, auditable v3 candidate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import SidecarError, configure_utf8_stdio
from v3lib import prepare_semantic_candidate


def _resolve_workdir(target: Path, explicit_workdir: Path | None) -> Path:
    if explicit_workdir is not None:
        return explicit_workdir.expanduser().resolve()
    resolved = target.expanduser().resolve()
    if resolved.is_dir() or resolved.name.endswith(".grammar-work"):
        return resolved
    if resolved.suffix.lower() == ".lrc":
        return (resolved.parent / f"{resolved.stem}.grammar-work").resolve()
    return resolved.parent


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description=(
            "Validate a Schema v3 semantic draft, exact repetition completion, and frozen "
            "bilingual lyrics; write analysis-candidate.json and analysis-candidate.sha256."
        )
    )
    parser.add_argument(
        "targets",
        type=Path,
        nargs="+",
        help="<workdir>, <song.lrc>, or <bilingual-lyrics.frozen.json> (single or batch)",
    )
    parser.add_argument("--workdir", type=Path, help="<song>.grammar-work directory (single file only)")
    parser.add_argument("--bilingual", type=Path, help="bilingual-lyrics.frozen.json (single file only)")
    parser.add_argument("--draft", type=Path, help="semantic-draft.json (single file only)")
    parser.add_argument("--candidate", type=Path, help="Candidate output (single file only)")
    parser.add_argument("--candidate-hash", type=Path, help="Hash output (single file only)")
    parser.add_argument(
        "--learner-language",
        required=True,
        help="Target learner language, e.g. zh-CN.",
    )
    args = parser.parse_args()

    single = len(args.targets) == 1
    if not single and any(
        opt is not None for opt in (args.workdir, args.bilingual, args.draft, args.candidate, args.candidate_hash)
    ):
        print("ERROR: single-target overrides cannot be used with multiple targets.", file=sys.stderr)
        return 2

    fail_count = 0
    for item in args.targets:
        workdir = _resolve_workdir(item, args.workdir if single else None)
        frozen_bilingual = (
            args.bilingual.expanduser().resolve()
            if (single and args.bilingual is not None)
            else None
        )
        draft_path = args.draft if (single and args.draft is not None) else None
        candidate_path = args.candidate if (single and args.candidate is not None) else None
        candidate_hash_path = args.candidate_hash if (single and args.candidate_hash is not None) else None

        try:
            candidate, report = prepare_semantic_candidate(
                workdir,
                draft_path,
                learner_language=args.learner_language,
                frozen_bilingual_path=frozen_bilingual,
                candidate_path=candidate_path,
                candidate_hash_path=candidate_hash_path,
            )
            out_cand = candidate_path or (workdir / "analysis-candidate.json")
            print(f"written: {out_cand}")
            print(f"candidateHash: {report['candidateHash']}")
            print(f"repetitionGroups: {len(candidate['repetitionGroups'])}")
            print(f"validationReport: {workdir / 'validation-report.json'}")
            if single:
                print(json.dumps(report, ensure_ascii=False, indent=2))
        except SidecarError as exc:
            print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
            print(f"validationReport: {workdir / 'validation-report.json'}", file=sys.stderr)
            fail_count += 1
        except Exception as exc:
            print(f"ERROR: failed on {item.name}: {exc}", file=sys.stderr)
            fail_count += 1

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
