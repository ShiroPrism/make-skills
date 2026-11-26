#!/usr/bin/env python3
"""Offline Schema v3, occurrence, meaning, and reference validation."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import (
    SCHEMA_VERSION,
    SidecarError,
    assert_distinct_paths,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    read_json,
    write_json_atomic,
)
from v3lib import validate_grammar_analysis_v3


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Validate a Schema v3 lyrics grammar sidecar or semantic draft."
    )
    parser.add_argument("sidecar", type=Path, help="Sidecar or draft JSON")
    parser.add_argument(
        "--bilingual",
        type=Path,
        help="Frozen bilingual-lyrics(.frozen).json for source content parity checks",
    )
    parser.add_argument(
        "--learner-language",
        help="Require extensions.learnerLanguage to equal this language.",
    )
    parser.add_argument("--report", type=Path, help="Write a validation report")
    args = parser.parse_args()

    bilingual = None
    try:
        raw_sidecar_path = args.sidecar.expanduser()
        if raw_sidecar_path.is_symlink():
            raise SidecarError("unsupported_source", "Symlinked sidecars are not supported.")
        sidecar_path = raw_sidecar_path.resolve()
        bilingual_path = args.bilingual.expanduser() if args.bilingual is not None else None
        report_path = args.report.expanduser() if args.report is not None else None
        assert_distinct_paths(
            ("sidecar", sidecar_path),
            ("bilingual lyrics", bilingual_path),
            ("validation report", report_path),
        )
        if bilingual_path is not None:
            bilingual = load_bilingual_lyrics(bilingual_path)
        document = read_json(sidecar_path)
        issues = validate_grammar_analysis_v3(
            document,
            bilingual=bilingual,
            require_bilingual=bilingual is not None,
            learner_language=args.learner_language,
        )
        report = {
            "ok": not issues,
            "schemaVersion": SCHEMA_VERSION,
            "errors": [issue.as_dict() for issue in issues],
            "contentHash": bilingual["contentHash"] if bilingual is not None else None,
            "sidecar": sidecar_path.name,
        }
        if report_path is not None:
            write_json_atomic(report_path, report, replace=True)
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 2

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if not issues else 1


if __name__ == "__main__":
    raise SystemExit(main())
