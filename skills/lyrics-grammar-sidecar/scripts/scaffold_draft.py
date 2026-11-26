#!/usr/bin/env python3
"""Pre-generate a Schema v3 semantic-draft.json skeleton from bilingual-lyrics.json and blocks-plan.json."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from resolve_spans import resolve_draft_spans
from sidecarlib import (
    SIDECAR_SCHEMA_ID,
    SCHEMA_VERSION,
    SidecarError,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    write_json_atomic,
)
from v3lib import (
    candidate_groups,
    discover_repetition_candidates,
    validate_grammar_analysis_v3,
)


def detect_language(text: str) -> str:
    """Detect coarse language code for code-point spans."""
    if re.search(r"[\u3040-\u30ff]", text):
        return "ja"
    if re.search(r"[\uac00-\ud7af]", text):
        return "ko"
    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    return "en"


def load_blocks_plan(
    plan_path: Path,
    learning_lines: list[dict],
) -> list[tuple[list[dict], str]]:
    """Parse blocks-plan.json into list of (block_lines, custom_meaning)."""
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

    result: list[tuple[list[dict], str]] = []
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
                elif re.match(r"^l_\d+\s*-\s*l_\d+$", s_strip):
                    start_id, end_id = [p.strip() for p in s_strip.split("-", 1)]
                    if start_id not in lines_by_id or end_id not in lines_by_id:
                        raise SidecarError(
                            "invalid_blocks_plan",
                            f"Block {b_idx}: lineId range {s_strip} out of bounds.",
                        )
                    start_ord = lines_by_id[start_id]["sourceOrder"]
                    end_ord = lines_by_id[end_id]["sourceOrder"]
                    if end_ord < start_ord:
                        raise SidecarError(
                            "invalid_blocks_plan",
                            f"Block {b_idx}: reversed lineId range {s_strip}.",
                        )
                    for ord_idx in range(start_ord, end_ord + 1):
                        resolved_lines.append(lines_by_order[ord_idx])
                elif "-" in s_strip and re.match(r"^\d+\s*-\s*\d+$", s_strip):
                    start_str, end_str = s_strip.split("-")
                    start_n, end_n = int(start_str.strip()), int(end_str.strip())
                    for n in range(start_n, end_n + 1):
                        l = lines_by_1based.get(n) or lines_by_order.get(n)
                        if l is None:
                            raise SidecarError(
                                "invalid_blocks_plan",
                                f"Block {b_idx}: line range {s_strip} index {n} not found.",
                            )
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
            f"Blocks plan missed {len(missing)} line(s): {missing_preview}. Every lyric line must belong to a block.",
        )

    return result


def scaffold_draft_document(
    workdir: Path,
    bilingual_path: Path,
    learner_language: str = "zh-CN",
    auto_discover_repetitions: bool = False,
    blocks_plan_path: Path | None = None,
) -> tuple[dict, list]:
    """Build a Schema v3 compliant initial semantic draft (pure content, zero timestamps)."""
    if not bilingual_path.is_file():
        raise SidecarError("file_not_found", f"Bilingual lyrics file not found: {bilingual_path}")

    bilingual = load_bilingual_lyrics(bilingual_path)

    lines: list[dict] = []
    source_langs: set[str] = set()
    for l in bilingual["lines"]:
        text = l["text"]
        lang = detect_language(text)
        source_langs.add(lang)
        lines.append(
            {
                "lineId": l["lineId"],
                "sourceOrder": l["sourceOrder"],
                "text": text,
                "fingerprint": l["fingerprint"],
                "role": "text",
                "language": lang,
                "languageSpans": [{"start": 0, "end": len(text), "language": lang}],
            }
        )

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
            f"Generate blocks-plan.json from bilingual-lyrics.json (or via lyrics-translator Dual-Track Mode) before scaffolding.",
        )

    blocks: list[dict] = []
    meaning_units: list[dict] = []
    line_sig_to_mu: dict[tuple[str, ...], dict] = {}

    def make_block(b_lines: list[dict], counter: int, custom_meaning: str) -> dict:
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
            canonical_mu["occurrences"].append(
                {
                    "occurrenceId": muo_id,
                    "blockId": bid,
                    "sourceSegments": source_segs,
                }
            )
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

        return {
            "blockId": bid,
            "lineIds": [l["lineId"] for l in b_lines],
            "meaning": {"parts": [{"meaningUnitOccurrenceId": muo_id}]},
            "labels": [],
            "confidence": 0.95,
        }

    plan_groups = load_blocks_plan(effective_plan, lines)
    for counter, (b_lines, custom_meaning) in enumerate(plan_groups, start=1):
        blocks.append(make_block(b_lines, counter, custom_meaning))

    draft = {
        "schema": SIDECAR_SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "source": {
            "sourceLanguages": sorted(source_langs) or ["en"],
            "lineCount": len(lines),
            "contentHash": bilingual["contentHash"],
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

    resolve_draft_spans(draft, bilingual)

    if auto_discover_repetitions:
        candidates = discover_repetition_candidates(draft, bilingual, learner_language=learner_language)
        draft["repetitionGroups"] = candidate_groups(candidates)

    issues = validate_grammar_analysis_v3(
        draft,
        bilingual=bilingual,
        require_bilingual=True,
        learner_language=learner_language,
    )
    return draft, issues


def _default_bilingual_path(workdir: Path) -> Path:
    frozen = workdir / "bilingual-lyrics.frozen.json"
    return frozen if frozen.is_file() else (workdir / "bilingual-lyrics.json")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Scaffold a Schema v3 semantic-draft.json from bilingual-lyrics.json and blocks-plan.json."
    )
    parser.add_argument(
        "target",
        type=Path,
        help="workdir, bilingual-lyrics(.frozen).json, or source .lrc path (infers <stem>.grammar-work)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        help="<song>.grammar-work directory",
    )
    parser.add_argument(
        "--bilingual",
        type=Path,
        help="Path to bilingual-lyrics(.frozen).json",
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
        bilingual_path = args.bilingual.expanduser().resolve() if args.bilingual else None

        if target.is_dir() or target.name.endswith(".grammar-work"):
            workdir = workdir or target
        elif target.suffix.lower() == ".lrc":
            workdir = workdir or (target.parent / f"{target.stem}.grammar-work").resolve()
        elif target.suffix.lower() == ".json":
            bilingual_path = bilingual_path or target
            workdir = workdir or target.parent
        else:
            workdir = workdir or target

        if not workdir.exists():
            workdir.mkdir(parents=True, exist_ok=True)
        if bilingual_path is None:
            bilingual_path = _default_bilingual_path(workdir)

        output_path = args.output.expanduser().resolve() if args.output else workdir / "semantic-draft.json"
        if output_path.exists() and not args.replace:
            raise SidecarError("output_exists", f"Output already exists (use --replace): {output_path}")

        blocks_plan = args.blocks_plan.expanduser().resolve() if args.blocks_plan else None
        draft, issues = scaffold_draft_document(
            workdir=workdir,
            bilingual_path=bilingual_path,
            learner_language=args.learner_language,
            auto_discover_repetitions=args.auto_repetitions,
            blocks_plan_path=blocks_plan,
        )

        write_json_atomic(output_path, draft, replace=args.replace)
        print(
            f"[OK] Scaffolded semantic-draft.json (v3): {len(draft['lines'])} lines, "
            f"{len(draft['blocks'])} blocks, {len(draft['meaningUnits'])} meaning units."
        )
        if issues:
            print(f"[WARN] Initial scaffold has {len(issues)} validation notices:")
            for issue in issues[:5]:
                print(f"  - {issue.code}: {issue.message}")
        else:
            print("[PASS] Initial scaffold passed 100% of Schema v3 validation rules.")

        line_by_id = {line["lineId"]: line for line in draft["lines"]}
        print("\n--- DRAFT INDEX (for enrichment.json) ---")
        for block in draft["blocks"]:
            bid = block["blockId"]
            b_lids = block.get("lineIds", [])
            if b_lids:
                lid_range = f"{b_lids[0]}..{b_lids[-1]}" if len(b_lids) > 1 else b_lids[0]
                print(f"[{bid}] {lid_range} ({len(b_lids)} line{'s' if len(b_lids) != 1 else ''})")
            for lid in b_lids:
                line_obj = line_by_id.get(lid)
                if line_obj:
                    cp_len = len(line_obj["text"])
                    print(f"  {line_obj['sourceOrder'] + 1} | {lid} ({cp_len} cp) | {line_obj['text']}")
        if draft.get("repetitionGroups"):
            print("\n--- REPETITION GROUPS ---")
            for rep in draft["repetitionGroups"]:
                occ_parts = []
                sample_text = ""
                for occ in rep.get("occurrences", []):
                    seg_ids = [s.get("lineId", "") for s in occ.get("sourceSegments", [])]
                    if not sample_text:
                        sample_text = "".join(s.get("text", "") for s in occ.get("sourceSegments", []))
                    occ_parts.append(f"{occ.get('blockId', '')} ({','.join(seg_ids)})")
                print(f"{rep.get('repetitionId', '')}: {' == '.join(occ_parts)} | {sample_text}")
        return 0
    except SidecarError as exc:
        print(f"ERROR [{exc.code}]: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR [scaffold_error]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
