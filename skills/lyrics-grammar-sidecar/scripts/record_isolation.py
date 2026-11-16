#!/usr/bin/env python3
"""Record a stage-bound v2 child transcript isolation proof."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sidecarlib import (
    ISOLATION_METHODS,
    ISOLATION_STAGES,
    SidecarError,
    assert_distinct_paths,
    configure_utf8_stdio,
    load_projection,
    pretty_json,
    write_json_atomic,
)
from v2lib import build_isolation_proof_v2


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Record the separate-transcript proof required for a v2 stage."
    )
    parser.add_argument(
        "target",
        type=Path,
        nargs="?",
        default=None,
        help="source-projection.json, workdir, or LRC file",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="<song>.grammar-work directory",
    )
    parser.add_argument(
        "--stage",
        required=True,
        choices=sorted(ISOLATION_STAGES),
        help="Grammar-analysis or semantic-audit stage",
    )
    parser.add_argument(
        "--artifact",
        type=Path,
        help="Artifact produced by the child (draft for grammar, audit report for audit)",
    )
    parser.add_argument(
        "--method",
        choices=sorted(ISOLATION_METHODS),
        default="native-subagent",
        help="Harness that supplies a separate transcript (default: native-subagent)",
    )
    parser.add_argument(
        "--child-transcript-id",
        required=True,
        help="ID of the fresh child transcript",
    )
    parser.add_argument(
        "--parent-transcript-id",
        help="ID of the invoking transcript, if the harness exposes it",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination isolation proof JSON",
    )
    parser.add_argument("--replace", action="store_true")
    args = parser.parse_args()

    try:
        target = args.target.expanduser().resolve() if args.target is not None else None
        workdir = args.workdir.expanduser().resolve() if args.workdir is not None else None

        projection_path: Path | None = None
        if target is not None:
            if target.is_dir() or target.name.endswith(".grammar-work"):
                workdir = workdir or target
                projection_path = workdir / "source-projection.json"
            elif target.suffix.lower() == ".lrc":
                workdir = workdir or (target.parent / f"{target.stem}.grammar-work").resolve()
                projection_path = workdir / "source-projection.json"
            elif target.name == "source-projection.json" or target.suffix.lower() == ".json":
                projection_path = target
                workdir = workdir or target.parent
            else:
                if target.is_file():
                    projection_path = target
                    workdir = workdir or target.parent
                else:
                    workdir = workdir or target
                    projection_path = workdir / "source-projection.json"
        elif workdir is not None:
            projection_path = workdir / "source-projection.json"
        else:
            raise SidecarError("missing-target", "Either a target path or --workdir must be provided.")

        if projection_path is None:
            projection_path = (workdir / "source-projection.json") if workdir else Path("source-projection.json")

        artifact_path = args.artifact.expanduser().resolve() if args.artifact is not None else None
        if artifact_path is None:
            if workdir is None:
                raise SidecarError("missing-artifact", "--artifact is required when workdir cannot be inferred.")
            if args.stage == "grammar-analysis":
                artifact_path = workdir / "semantic-draft.json"
            elif args.stage == "semantic-audit":
                artifact_path = workdir / "semantic-audit.json"
            else:
                raise SidecarError("missing-artifact", f"Unknown stage {args.stage}.")

        output_path = args.output.expanduser().resolve() if args.output is not None else None
        if output_path is None:
            if workdir is None:
                raise SidecarError("missing-output", "--output is required when workdir cannot be inferred.")
            if args.stage == "grammar-analysis":
                output_path = workdir / "isolation-grammar-analysis.json"
            elif args.stage == "semantic-audit":
                output_path = workdir / "isolation-semantic-audit.json"
            else:
                raise SidecarError("missing-output", f"Unknown stage {args.stage}.")

        assert_distinct_paths(
            ("source projection", projection_path),
            ("child artifact", artifact_path),
            ("isolation proof", output_path),
        )
        projection = load_projection(projection_path)
        proof = build_isolation_proof_v2(
            projection,
            args.stage,
            artifact_path,
            args.method,
            child_transcript_id=args.child_transcript_id,
            parent_transcript_id=args.parent_transcript_id,
        )
        write_json_atomic(output_path, proof, replace=args.replace)
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 2
    print(pretty_json(proof), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
