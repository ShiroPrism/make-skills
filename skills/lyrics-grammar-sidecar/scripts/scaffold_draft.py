#!/usr/bin/env python3
"""Pre-generate a Schema v2 semantic-draft.json skeleton from source projection and frozen translated LRC.

This deterministic tool creates the complete baseline lines, monotonic blocks, and initial
meaning units synthesized from the frozen translated.lrc. It eliminates hundreds of turns
and millions of tokens previously wasted by subagents manually reconstructing JSON structure.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    load_projection,
    parse_lrc_rows,
    write_json_atomic,
)
from resolve_spans import resolve_draft_spans
from v2lib import (
    candidate_groups,
    discover_repetition_candidates,
    validate_grammar_analysis_v2,
)


def detect_language(text: str) -> str:
    """Detect coarse language code for code-point spans."""
    if re.search(r"[\u3040-\u30ff]", text):  # Hiragana or Katakana
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):  # Hangul
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):  # CJK Ideographs
        return "zh"
    return "en"


def scaffold_draft_document(
    workdir: Path,
    projection_path: Path,
    translated_lrc_path: Path | None = None,
    learner_language: str = "zh-CN",
    auto_discover_repetitions: bool = False,
) -> tuple[dict, list]:
    """Build a Schema v2 compliant initial semantic draft."""
    if not projection_path.is_file():
        raise SidecarError("file_not_found", f"Projection file not found: {projection_path}")

    projection = load_projection(projection_path)

    trans_map: dict[int, str] = {}
    if translated_lrc_path and translated_lrc_path.is_file():
        rows = parse_lrc_rows(translated_lrc_path)
        seen_times: set[int] = set()
        for r in rows:
            t = r.timestamps[0] if r.timestamps else 0
            if t not in seen_times:
                seen_times.add(t)
            else:
                trans_map[t] = r.text

    lines: list[dict] = []
    source_langs: set[str] = set()
    for l in projection["lines"]:
        text = l["text"]
        lang = l.get("language") or detect_language(text)
        source_langs.add(lang)
        line_obj = {
            "lineId": l["lineId"],
            "sourceOrder": l["sourceOrder"],
            "timeMs": l["timeMs"],
            "text": text,
            "fingerprint": l["fingerprint"],
            "role": "text",
            "language": lang,
            "languageSpans": [{"start": 0, "end": len(text), "language": lang}],
        }
        lines.append(line_obj)

    blocks: list[dict] = []
    meaning_units: list[dict] = []

    # Check for metadata line(s) at start (Title, Artist, Credits)
    start_idx = 0
    if len(lines) > 0:
        first = lines[0]
        first_text_lower = first["text"].lower()
        is_meta = (
            first["timeMs"] <= 1000
            or first.get("role") == "metadata"
            or " - " in first["text"]
            or any(kw in first_text_lower for kw in ["lyrics by", "composed by", "written by", "produced by"])
        )
        if is_meta:
            meta_line = first
            b_meta = {
                "blockId": "b_meta",
                "lineIds": [meta_line["lineId"]],
                "startTimeMs": meta_line["timeMs"],
                "endTimeMs": lines[1]["timeMs"] if len(lines) > 1 else meta_line["timeMs"] + 1000,
                "meaning": {
                    "parts": [{"meaningUnitOccurrenceId": "muo_meta"}]
                },
                "labels": [{"namespace": "discourse", "key": "metadata"}],
                "confidence": 1.0,
            }
            mu_meta = {
                "meaningUnitId": "mu_meta",
                "text": "歌曲标题与演职员信息。",
                "labels": [{"namespace": "discourse", "key": "metadata"}],
                "confidence": 1.0,
                "occurrences": [
                    {
                        "occurrenceId": "muo_meta",
                        "blockId": "b_meta",
                        "sourceSegments": [
                            {
                                "lineId": meta_line["lineId"],
                                "start": 0,
                                "end": len(meta_line["text"]),
                                "text": meta_line["text"],
                            }
                        ],
                    }
                ],
            }
            blocks.append(b_meta)
            meaning_units.append(mu_meta)
            start_idx = 1

    curr_block_lines: list[dict] = []
    block_counter = 1
    line_sig_to_mu: dict[tuple[str, ...], dict] = {}

    def make_block(b_lines: list[dict], counter: int) -> dict:
        bid = f"b_{counter:02d}"
        muo_id = f"muo_{bid}"

        b_lines_sig = tuple(l["text"] for l in b_lines)
        source_segs = [
            {
                "lineId": l["lineId"],
                "start": 0,
                "end": len(l["text"]),
                "text": l["text"],
            }
            for l in b_lines
        ]

        if b_lines_sig in line_sig_to_mu:
            canonical_mu = line_sig_to_mu[b_lines_sig]
            canonical_mu["occurrences"].append({
                "occurrenceId": muo_id,
                "blockId": bid,
                "sourceSegments": source_segs,
            })
        else:
            mu_id = f"mu_{bid}"
            trans_texts = []
            for l in b_lines:
                t_text = trans_map.get(l["timeMs"], "").strip()
                if t_text:
                    t_text = re.sub(r"[，。！？；、,.!?]+$", "", t_text)
                    trans_texts.append(t_text)
            synth_text = "，".join(trans_texts) + "。" if trans_texts else "乐句表达。"

            mu = {
                "meaningUnitId": mu_id,
                "text": synth_text,
                "labels": [],
                "confidence": 0.95,
                "occurrences": [
                    {
                        "occurrenceId": muo_id,
                        "blockId": bid,
                        "sourceSegments": source_segs,
                    }
                ],
            }
            line_sig_to_mu[b_lines_sig] = mu
            meaning_units.append(mu)

        b = {
            "blockId": bid,
            "lineIds": [l["lineId"] for l in b_lines],
            "startTimeMs": b_lines[0]["timeMs"],
            "endTimeMs": b_lines[-1]["timeMs"] + 2000,
            "meaning": {
                "parts": [{"meaningUnitOccurrenceId": muo_id}]
            },
            "labels": [],
            "confidence": 0.95,
        }
        return b

    for i in range(start_idx, len(lines)):
        l = lines[i]
        if curr_block_lines:
            gap = l["timeMs"] - curr_block_lines[-1]["timeMs"]
            if gap >= 4500 or len(curr_block_lines) >= 6:
                blocks.append(make_block(curr_block_lines, block_counter))
                block_counter += 1
                curr_block_lines = []
        curr_block_lines.append(l)

    if curr_block_lines:
        blocks.append(make_block(curr_block_lines, block_counter))

    # Refine block end times
    for i in range(len(blocks) - 1):
        next_start = blocks[i + 1]["startTimeMs"]
        if blocks[i]["endTimeMs"] > next_start:
            blocks[i]["endTimeMs"] = next_start

    draft = {
        "schema": "sakurauta.lyrics-grammar-analysis",
        "schemaVersion": 2,
        "source": {
            "lrcFile": projection["lrcFile"],
            "songId": projection["songId"],
            "sourceLanguages": sorted(source_langs) or ["en"],
            "lineCount": len(lines),
            "lrcProjectionHash": projection["lrcProjectionHash"],
        },
        "lines": lines,
        "repetitionGroups": [],
        "meaningUnits": meaning_units,
        "blocks": blocks,
        "phrases": [],
        "relations": [],
        "grammarNotes": [],
        "uncertainties": [],
        "extensions": {
            "learnerLanguage": learner_language,
        },
    }

    resolve_draft_spans(draft, projection)

    if auto_discover_repetitions:
        candidates = discover_repetition_candidates(draft, projection, learner_language=learner_language)
        draft["repetitionGroups"] = candidate_groups(candidates)

    issues = validate_grammar_analysis_v2(
        draft,
        projection=projection,
        expected_lrc_file=projection.get("lrcFile"),
        learner_language=learner_language,
    )
    return draft, issues


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Scaffold a Schema v2 semantic-draft.json from source projection and translated LRC."
    )
    parser.add_argument(
        "target",
        type=Path,
        help="source-projection.json, workdir, or source LRC file",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="<song>.grammar-work directory",
    )
    parser.add_argument(
        "--learner-language",
        default="zh-CN",
        help="Target learner language (default: zh-CN)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Destination path (default: <workdir>/semantic-draft.json)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Overwrite existing output file",
    )
    parser.add_argument(
        "--auto-repetitions",
        action="store_true",
        help="Pre-populate repetition groups via discovery",
    )
    args = parser.parse_args()

    try:
        target = args.target.expanduser().resolve()
        workdir = args.workdir.expanduser().resolve() if args.workdir else None

        if target.is_dir() or target.name.endswith(".grammar-work"):
            workdir = workdir or target
            proj_path = workdir / "source-projection.json"
        elif target.suffix.lower() == ".lrc":
            workdir = workdir or (target.parent / f"{target.stem}.grammar-work").resolve()
            proj_path = workdir / "source-projection.json"
        elif target.name == "source-projection.json" or target.suffix.lower() == ".json":
            proj_path = target
            workdir = workdir or target.parent
        else:
            workdir = workdir or target
            proj_path = workdir / "source-projection.json"

        if not workdir.exists():
            workdir.mkdir(parents=True, exist_ok=True)

        translated_lrc = workdir / "translated.lrc"
        output_path = args.output.expanduser().resolve() if args.output else workdir / "semantic-draft.json"

        if output_path.exists() and not args.replace:
            raise SidecarError("output_exists", f"Output already exists (use --replace): {output_path}")

        draft, issues = scaffold_draft_document(
            workdir=workdir,
            projection_path=proj_path,
            translated_lrc_path=translated_lrc if translated_lrc.exists() else None,
            learner_language=args.learner_language,
            auto_discover_repetitions=args.auto_repetitions,
        )

        write_json_atomic(output_path, draft, replace=args.replace)
        print(f"[OK] Scaffolded semantic-draft.json: {len(draft['lines'])} lines, {len(draft['blocks'])} blocks, {len(draft['meaningUnits'])} meaning units.")
        if issues:
            print(f"[WARN] Initial scaffold has {len(issues)} validation notices:")
            for issue in issues[:5]:
                print(f"  - {issue.code}: {issue.message}")
        else:
            print("[PASS] Initial scaffold passed 100% of Schema v2 validation rules.")
        return 0
    except SidecarError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR [scaffold_error]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
