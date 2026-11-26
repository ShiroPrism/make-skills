#!/usr/bin/env python3
"""Discover deterministic maximal exact repetition candidates from a Schema v3 draft."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    assert_distinct_paths,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    read_json,
    write_json_atomic,
)
from v3lib import (
    _extract_excluded_repetitions,
    candidate_groups,
    discover_repetition_candidates,
    validate_grammar_analysis_v3,
)


def _default_bilingual(workdir: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.expanduser()
    frozen = workdir / "bilingual-lyrics.frozen.json"
    return frozen if frozen.is_file() else (workdir / "bilingual-lyrics.json")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Find exact repetitions for Schema v3 Semantic Draft Contract."
    )
    parser.add_argument("draft", type=Path, help="semantic-draft.json")
    parser.add_argument(
        "--bilingual",
        type=Path,
        help="bilingual-lyrics(.frozen).json (default: auto-inferred from workdir)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="<song>.grammar-work directory (default: draft parent)",
    )
    parser.add_argument(
        "--learner-language",
        help="Optional learner-language validation, e.g. zh-CN.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Candidate path (default: <workdir>/repetition-candidates.json)",
    )
    parser.add_argument("--replace", action="store_true")
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Update repetitionGroups in the semantic draft JSON in-place",
    )
    parser.add_argument(
        "--exclude",
        action="append",
        default=[],
        help="Exclude a spurious candidate as '<repetitionId>=<reason>' (repeatable; stored in extensions.excludedRepetitions)",
    )
    parser.add_argument(
        "--check-draft",
        action="store_true",
        help="When --in-place is set, validate the updated semantic draft (including shared-occurrence completeness) and exit non-zero on errors",
    )
    args = parser.parse_args()

    draft_path = args.draft.expanduser()
    workdir = (args.workdir or draft_path.parent).expanduser().resolve()
    bilingual_path = _default_bilingual(workdir, args.bilingual)
    output = (args.output or (workdir / "repetition-candidates.json")).expanduser()
    try:
        assert_distinct_paths(
            ("semantic draft", draft_path),
            ("bilingual lyrics", bilingual_path),
            ("repetition candidates", output),
        )
        bilingual = load_bilingual_lyrics(bilingual_path)
        draft = read_json(draft_path)
        candidates = discover_repetition_candidates(
            draft,
            bilingual,
            learner_language=args.learner_language,
        )
        if args.exclude:
            extensions = draft.setdefault("extensions", {})
            existing = list(extensions.get("excludedRepetitions", []))
            by_id = {
                item["repetitionId"]: item
                for item in existing
                if isinstance(item, dict) and isinstance(item.get("repetitionId"), str)
            }
            for spec in args.exclude:
                if "=" not in spec:
                    raise SidecarError(
                        "invalid_excluded_repetitions",
                        f"Expected --exclude '<repetitionId>=<reason>', got {spec!r}.",
                    )
                rep_id, reason = spec.split("=", 1)
                rep_id, reason = rep_id.strip(), reason.strip()
                by_id[rep_id] = {"repetitionId": rep_id, "reason": reason}
            extensions["excludedRepetitions"] = list(by_id.values())

        all_candidate_ids = {
            c["repetitionId"]
            for c in candidates.get("candidates", [])
            if isinstance(c, dict) and isinstance(c.get("repetitionId"), str)
        }
        excluded_ids, exclusion_issues = _extract_excluded_repetitions(draft, all_candidate_ids)
        if exclusion_issues:
            raise SidecarError(
                exclusion_issues[0].code,
                exclusion_issues[0].message,
                exclusion_issues[0].path,
            )

        changed = write_json_atomic(output, candidates, replace=args.replace)
        if args.in_place:
            groups = candidate_groups(candidates, excluded_ids=excluded_ids)
            draft["repetitionGroups"] = groups
            write_json_atomic(draft_path, draft, replace=True)
            print(
                f"updated: {draft_path} (repetitionGroups: {len(groups)}, excluded: {len(excluded_ids)})"
            )
            draft_issues = validate_grammar_analysis_v3(
                draft,
                bilingual=bilingual,
                require_bilingual=True,
                learner_language=args.learner_language,
            )
            if draft_issues:
                level = "ERROR" if args.check_draft else "WARNING"
                for issue in draft_issues:
                    print(f"{level} [{issue.code}] {issue.path}: {issue.message}", file=sys.stderr)
                if any(
                    issue.code in {"shared-occurrence-incomplete", "shared-occurrence-mismatch"}
                    for issue in draft_issues
                ):
                    print(
                        "HINT: When a block only partially overlaps a repetitionGroup, split its "
                        "meaningUnits and blocks[].meaning.parts into the shared repetition span "
                        "and the non-overlapping remainder in enrichment.json, then re-run "
                        "resolve_spans.py and discover_repetitions.py.",
                        file=sys.stderr,
                    )
                if args.check_draft:
                    return 2
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 2

    action = "written" if changed else "unchanged"
    print(f"{action}: {output}")
    print(f"candidates: {len(candidates['candidates'])}")
    print(json.dumps(candidates["candidates"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
