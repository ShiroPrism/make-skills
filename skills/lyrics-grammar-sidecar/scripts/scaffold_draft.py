#!/usr/bin/env python3
"""Pre-generate a Schema v2 semantic-draft.json skeleton from source projection and frozen translated LRC.

This deterministic tool creates the complete baseline lines, monotonic blocks, and initial
meaning units synthesized from the frozen translated.lrc. It eliminates hundreds of turns
and millions of tokens previously wasted by subagents manually reconstructing JSON structure.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    load_projection,
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


def load_blocks_plan(
    plan_path: Path,
    learning_lines: list[dict],
) -> list[tuple[list[dict], str]]:
    """Parse blocks-plan.json into list of (b_lines, custom_meaning)."""
    try:
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise SidecarError("invalid_blocks_plan", f"Failed to parse blocks plan: {exc}")

    raw_blocks = data.get("blocks", data) if isinstance(data, dict) else data
    if not isinstance(raw_blocks, list) or not raw_blocks:
        raise SidecarError("invalid_blocks_plan", "Blocks plan must contain a non-empty 'blocks' list.")

    lines_by_id = {l["lineId"]: l for l in learning_lines}
    lines_by_order = {l["sourceOrder"]: l for l in learning_lines}
    lines_by_1based = {i + 1: l for i, l in enumerate(learning_lines)}

    result: list[tuple[list[dict], str | None]] = []
    used_line_ids: set[str] = set()

    for b_idx, item in enumerate(raw_blocks):
        if isinstance(item, dict):
            specs = item.get("lines", [])
            custom_meaning = item.get("meaning") or item.get("text") or item.get("meaning_text")
        elif isinstance(item, list):
            specs = item
            custom_meaning = None
        else:
            raise SidecarError("invalid_blocks_plan", f"Block item {b_idx} must be a dict or list.")

        if not specs:
            continue

        resolved_lines: list[dict] = []
        for s in specs:
            if isinstance(s, int):
                if s in lines_by_1based and not (0 in lines_by_order and s == 0):
                    l = lines_by_1based.get(s) or lines_by_order.get(s)
                else:
                    l = lines_by_order.get(s) or lines_by_1based.get(s)
                if l is None:
                    raise SidecarError("invalid_blocks_plan", f"Block {b_idx}: line index {s} not found.")
                resolved_lines.append(l)
            elif isinstance(s, str):
                s_strip = s.strip()
                if s_strip in lines_by_id:
                    resolved_lines.append(lines_by_id[s_strip])
                elif "-" in s_strip and re.match(r"^\d+\s*-\s*\d+$", s_strip):
                    start_str, end_str = s_strip.split("-")
                    start_n, end_n = int(start_str.strip()), int(end_str.strip())
                    for n in range(start_n, end_n + 1):
                        l = lines_by_1based.get(n) or lines_by_order.get(n)
                        if l is None:
                            raise SidecarError("invalid_blocks_plan", f"Block {b_idx}: line range {s_strip} index {n} not found.")
                        resolved_lines.append(l)
                elif s_strip.isdigit():
                    n = int(s_strip)
                    l = lines_by_1based.get(n) or lines_by_order.get(n)
                    if l is None:
                        raise SidecarError("invalid_blocks_plan", f"Block {b_idx}: line number {n} not found.")
                    resolved_lines.append(l)
                else:
                    raise SidecarError("invalid_blocks_plan", f"Block {b_idx}: unrecognized line spec {s!r}")

        if not resolved_lines:
            continue

        resolved_lines.sort(key=lambda x: x["sourceOrder"])
        for l in resolved_lines:
            if l["lineId"] in used_line_ids:
                raise SidecarError("invalid_blocks_plan", f"Line {l['lineId']} ({l['text']}) used in multiple blocks.")
            used_line_ids.add(l["lineId"])
        if not custom_meaning or not str(custom_meaning).strip():
            raise SidecarError(
                "invalid_blocks_plan",
                f"Block {b_idx} must specify a non-empty literary 'meaning'.",
            )
        result.append((resolved_lines, str(custom_meaning).strip()))

    missing = [l for l in learning_lines if l["lineId"] not in used_line_ids]
    if missing:
        missing_preview = ", ".join(repr(l["text"]) for l in missing[:3])
        raise SidecarError(
            "invalid_blocks_plan",
            f"Blocks plan missed {len(missing)} line(s): {missing_preview}. Every non-metadata source line must belong to exactly one block.",
        )

    return result


def scaffold_draft_document(
    workdir: Path,
    projection_path: Path,
    translated_lrc_path: Path | None = None,
    learner_language: str = "zh-CN",
    auto_discover_repetitions: bool = False,
    blocks_plan_path: Path | None = None,
) -> tuple[dict, list]:
    """Build a Schema v2 compliant initial semantic draft."""
    if not projection_path.is_file():
        raise SidecarError("file_not_found", f"Projection file not found: {projection_path}")

    projection = load_projection(projection_path)

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
            first.get("role") == "metadata"
            or (
                first["timeMs"] == 0
                and (
                    " - " in first["text"]
                    or any(kw in first_text_lower for kw in ["lyrics by", "composed by", "written by", "produced by", "作词", "作詞", "作曲", "编曲", "編曲", "演唱", "artist", "title"])
                )
            )
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

    learning_lines = lines[start_idx:]
    block_counter = 1
    line_sig_to_mu: dict[tuple[str, ...], dict] = {}

    def make_block(b_lines: list[dict], counter: int, custom_meaning: str | None = None) -> dict:
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
            synth_text = custom_meaning.strip()
            if not re.search(r"[。！？!?…]$", synth_text):
                synth_text += "。"

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

    effective_plan = blocks_plan_path
    if effective_plan is None and workdir:
        cand_plan = workdir / "blocks-plan.json"
        if cand_plan.is_file():
            effective_plan = cand_plan

    if not effective_plan or not effective_plan.is_file():
        expected_path = effective_plan or (workdir / "blocks-plan.json" if workdir else Path("blocks-plan.json"))
        raise SidecarError(
            "missing_blocks_plan",
            f"blocks-plan.json is required ({expected_path} not found). "
            f"Every song must be processed via lyrics-translator (Dual-Track Mode) to produce blocks-plan.json with LLM-partitioned semantic stanzas and fluent meanings."
        )

    plan_groups = load_blocks_plan(effective_plan, learning_lines)
    for b_lines, custom_meaning in plan_groups:
        blocks.append(make_block(b_lines, block_counter, custom_meaning=custom_meaning))
        block_counter += 1

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
    parser.add_argument(
        "--blocks-plan",
        type=Path,
        help="Path to blocks-plan.json (default: <workdir>/blocks-plan.json; required)",
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

        blocks_plan = args.blocks_plan.expanduser().resolve() if args.blocks_plan else None

        draft, issues = scaffold_draft_document(
            workdir=workdir,
            projection_path=proj_path,
            translated_lrc_path=translated_lrc if translated_lrc.exists() else None,
            learner_language=args.learner_language,
            auto_discover_repetitions=args.auto_repetitions,
            blocks_plan_path=blocks_plan,
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
