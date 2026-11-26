#!/usr/bin/env python3
"""Extract timestamp-free, filtered bilingual-lyrics.json (or canonical lyric-index.txt) for Schema v3.

Supports three modes:
1. Line index preview: `--emit-index <song.lrc>` -> writes `<workdir>/lyric-index.txt` (`l_001 | <text>`).
2. Workflow handoff mode: `<song.lrc>` + translated `<song.lrc>.tmp.txt` (before lrc_merge.py).
3. External bilingual LRC adapter: `--from-bilingual-lrc <bilingual.lrc> ...`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    assert_distinct_paths,
    configure_utf8_stdio,
    extract_bilingual_from_bilingual_lrc,
    extract_bilingual_from_lrc_and_tmp,
    extract_source_index_from_lrc,
    write_json_atomic,
)


def _resolve_tmp_path(lrc_path: Path, explicit_tmp: Path | None) -> Path:
    if explicit_tmp is not None:
        return explicit_tmp.expanduser().resolve()
    candidates = [
        lrc_path.with_name(f"{lrc_path.name}.tmp.txt"),
        lrc_path.with_suffix(".tmp.txt"),
    ]
    for cand in candidates:
        if cand.is_file():
            return cand.resolve()
    return candidates[0].resolve()


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Extract timestamp-free bilingual-lyrics.json from LRC + .tmp.txt or an external bilingual LRC."
    )
    parser.add_argument(
        "lrc",
        type=Path,
        nargs="+",
        help="Local .lrc file(s)",
    )
    parser.add_argument(
        "--tmp",
        type=Path,
        help="Translated .tmp.txt file (single file only; defaults to <song.lrc>.tmp.txt)",
    )
    parser.add_argument(
        "--emit-index",
        action="store_true",
        help="Emit canonical filtered lyric-index.txt (l_001 | <text>) into workdir without requiring .tmp.txt",
    )
    parser.add_argument(
        "--from-bilingual-lrc",
        action="store_true",
        help="Strip timestamps from already-bilingual LRC file(s) instead of reading .tmp.txt",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="<song>.grammar-work directory (single file only)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output JSON or index path (single file only; default: <workdir>/bilingual-lyrics.json or lyric-index.txt)",
    )
    parser.add_argument(
        "--title-hint",
        help="Optional title-artist hint for <=2.5s header exclusion (single file only; defaults to LRC stem)",
    )
    parser.add_argument(
        "--source-language",
        action="append",
        dest="source_languages",
        help="Optional source language tag (repeatable)",
    )
    parser.add_argument(
        "--learner-language",
        help="Optional target learner language tag",
    )
    parser.add_argument("--replace", action="store_true", help="Overwrite a differing output file")
    args = parser.parse_args()

    if len(args.lrc) > 1 and (args.output is not None or args.workdir is not None or args.tmp is not None or args.title_hint is not None):
        print("ERROR: --output, --workdir, --tmp, and --title-hint can only be used with a single input file.", file=sys.stderr)
        return 2

    fail_count = 0
    for lrc_item in args.lrc:
        try:
            lrc_path = lrc_item.expanduser().resolve()
            workdir = (
                args.workdir.expanduser().resolve()
                if args.workdir is not None
                else (lrc_path.parent / f"{lrc_path.stem}.grammar-work").resolve()
            )
            if args.emit_index:
                index_out = (
                    args.output.expanduser().resolve()
                    if args.output is not None
                    else (workdir / "lyric-index.txt")
                )
                assert_distinct_paths(("source LRC", lrc_path), ("lyric index", index_out))
                indexed_lines = extract_source_index_from_lrc(
                    lrc_path,
                    title_hint=args.title_hint,
                )
                index_out.parent.mkdir(parents=True, exist_ok=True)
                rendered = "\n".join(
                    f"{entry['lineId']} | {entry['text']}" for entry in indexed_lines
                ) + "\n"
                index_out.write_text(rendered, encoding="utf-8", newline="\n")
                print(f"written: {index_out}")
                print(f"lines: {len(indexed_lines)}")
                continue

            output = (
                args.output.expanduser().resolve()
                if args.output is not None
                else (workdir / "bilingual-lyrics.json")
            )
            if args.from_bilingual_lrc:
                assert_distinct_paths(("bilingual LRC", lrc_path), ("bilingual output", output))
                doc = extract_bilingual_from_bilingual_lrc(
                    lrc_path,
                    title_hint=args.title_hint,
                    source_languages=args.source_languages,
                    learner_language=args.learner_language,
                )
            else:
                tmp_path = _resolve_tmp_path(lrc_path, args.tmp)
                assert_distinct_paths(
                    ("source LRC", lrc_path),
                    ("translated tmp", tmp_path),
                    ("bilingual output", output),
                )
                doc = extract_bilingual_from_lrc_and_tmp(
                    lrc_path,
                    tmp_path,
                    title_hint=args.title_hint,
                    source_languages=args.source_languages,
                    learner_language=args.learner_language,
                )

            changed = write_json_atomic(output, doc, replace=args.replace)
            translated_count = sum(
                1 for line in doc["lines"] if isinstance(line.get("translation"), str) and line["translation"].strip()
            )
            action = "written" if changed else "unchanged"
            print(f"{action}: {output}")
            print(f"contentHash: {doc['contentHash']}")
            print(f"lines: {doc['lineCount']}")
            print(f"translatedLines: {translated_count}")
        except SidecarError as exc:
            print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
            fail_count += 1
        except Exception as exc:
            print(f"ERROR: failed on {lrc_item}: {exc}", file=sys.stderr)
            fail_count += 1

    return 0 if fail_count == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
