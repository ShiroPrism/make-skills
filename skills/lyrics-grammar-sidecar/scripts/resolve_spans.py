#!/usr/bin/env python3
"""Resolve and verify Unicode code point spans for Schema v3 drafts and bilingual lyrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    read_json,
    write_json_atomic,
)


def resolve_line_span(line_text: str, surface: str) -> list[tuple[int, int]]:
    """Return all [start, end) code-point spans where surface occurs in line_text."""
    spans: list[tuple[int, int]] = []
    start = 0
    while True:
        pos = line_text.find(surface, start)
        if pos == -1:
            break
        spans.append((pos, pos + len(surface)))
        start = pos + 1
    return spans


def resolve_draft_spans(
    draft: dict[str, Any],
    bilingual: dict[str, Any],
) -> tuple[int, int, list[str]]:
    """Verify and fix code point spans in draft meaningUnits and phrases."""
    lines_by_id = {line["lineId"]: line["text"] for line in bilingual.get("lines", [])}

    resolved = 0
    errors = 0
    messages: list[str] = []

    def process_segments(item_id: str, occ_id: str, segments: list[dict[str, Any]]) -> None:
        nonlocal resolved, errors
        for seg_idx, seg in enumerate(segments):
            if not isinstance(seg, dict):
                continue
            line_id = seg.get("lineId")
            if line_id not in lines_by_id:
                messages.append(f"[{item_id}/{occ_id}] seg {seg_idx}: unknown lineId {line_id}")
                errors += 1
                continue
            line_text = lines_by_id[line_id]
            text = seg.get("text")
            if not isinstance(text, str):
                continue

            current_start = seg.get("start")
            current_end = seg.get("end")
            if (
                isinstance(current_start, int)
                and isinstance(current_end, int)
                and 0 <= current_start <= current_end <= len(line_text)
                and line_text[current_start:current_end] == text
            ):
                continue

            occurrences = resolve_line_span(line_text, text)
            if not occurrences:
                messages.append(
                    f"[{item_id}/{occ_id}] seg {seg_idx}: text '{text}' not found in line '{line_text}'"
                )
                errors += 1
            elif len(occurrences) == 1:
                start, end = occurrences[0]
                seg["start"] = start
                seg["end"] = end
                resolved += 1
                messages.append(
                    f"[{item_id}/{occ_id}] resolved span [{start}:{end}] for '{text}' on {line_id}"
                )
            else:
                matching = [span for span in occurrences if span[0] == current_start]
                if matching:
                    seg["start"], seg["end"] = matching[0]
                else:
                    messages.append(
                        f"[{item_id}/{occ_id}] seg {seg_idx}: ambiguous '{text}' appears {len(occurrences)} times in '{line_text}'"
                    )
                    errors += 1

    for mu in draft.get("meaningUnits", []):
        mu_id = mu.get("meaningUnitId", "unknown_mu")
        for occ in mu.get("occurrences", []):
            occ_id = occ.get("occurrenceId", "unknown_occ")
            process_segments(mu_id, occ_id, occ.get("sourceSegments", []))

    for phrase in draft.get("phrases", []):
        p_id = phrase.get("phraseId", "unknown_phrase")
        surface = phrase.get("surface")
        occurrences = phrase.get("occurrences", [])
        if (not isinstance(surface, str) or not surface) and occurrences:
            first_segs = occurrences[0].get("sourceSegments", [])
            derived = "".join(
                seg.get("text", "")
                for seg in first_segs
                if isinstance(seg, dict) and isinstance(seg.get("text"), str)
            )
            if derived:
                phrase["surface"] = derived
                surface = derived
        for occ in occurrences:
            occ_id = occ.get("occurrenceId", "unknown_occ")
            segs = occ.get("sourceSegments", [])
            if len(segs) == 1 and isinstance(surface, str) and not segs[0].get("text"):
                segs[0]["text"] = surface
            process_segments(p_id, occ_id, segs)

    return resolved, errors, messages


ALLOWED_ENRICHMENT_KEYS = frozenset(
    {
        "phrases",
        "grammarNotes",
        "relations",
        "uncertainties",
        "meaningUnits",
        "blocks",
        "excludedRepetitions",
    }
)

ALLOWED_BLOCK_PATCH_KEYS = frozenset({"blockId", "meaning", "labels", "register", "notes", "confidence"})


def merge_enrichment_into_draft(draft: dict[str, Any], enrichment: dict[str, Any]) -> list[str]:
    """Merge compact enrichment payload (phrases, grammarNotes, optional blocks/meaningUnits/excludedRepetitions) into draft."""
    if not isinstance(enrichment, dict):
        raise SidecarError("invalid_enrichment", "Enrichment payload must be a JSON object.")
    unknown_keys = set(enrichment.keys()) - ALLOWED_ENRICHMENT_KEYS
    if unknown_keys:
        raise SidecarError(
            "invalid_enrichment",
            f"Unsupported top-level key(s) in enrichment JSON: {sorted(unknown_keys)}. "
            f"Allowed: {sorted(ALLOWED_ENRICHMENT_KEYS)}",
        )
    merged_keys: list[str] = []
    for key in ("phrases", "grammarNotes", "relations", "uncertainties", "meaningUnits"):
        if key in enrichment:
            value = enrichment[key]
            if not isinstance(value, list):
                raise SidecarError("invalid_enrichment", f"Enrichment field '{key}' must be an array.")
            draft[key] = value
            merged_keys.append(f"{key}={len(value)}")

    if "blocks" in enrichment:
        block_patches = enrichment["blocks"]
        if not isinstance(block_patches, list):
            raise SidecarError("invalid_enrichment", "Enrichment field 'blocks' must be an array.")
        blocks_by_id = {
            b["blockId"]: b
            for b in draft.get("blocks", [])
            if isinstance(b, dict) and isinstance(b.get("blockId"), str)
        }
        for idx, patch in enumerate(block_patches):
            if not isinstance(patch, dict):
                raise SidecarError("invalid_enrichment", f"Enrichment blocks[{idx}] must be an object.")
            bad_patch_keys = set(patch.keys()) - ALLOWED_BLOCK_PATCH_KEYS
            if bad_patch_keys:
                raise SidecarError(
                    "invalid_enrichment",
                    f"Unsupported key(s) in enrichment blocks[{idx}]: {sorted(bad_patch_keys)}. "
                    f"Allowed: {sorted(ALLOWED_BLOCK_PATCH_KEYS)}",
                )
            bid = patch.get("blockId")
            if not isinstance(bid, str) or bid not in blocks_by_id:
                raise SidecarError(
                    "invalid_enrichment",
                    f"Enrichment blocks[{idx}].blockId {bid!r} does not match any scaffolded block.",
                )
            target_block = blocks_by_id[bid]
            for field in ("meaning", "labels", "register", "notes", "confidence"):
                if field in patch:
                    target_block[field] = patch[field]
        merged_keys.append(f"blocks={len(block_patches)}")

    if "excludedRepetitions" in enrichment:
        exclusions = enrichment["excludedRepetitions"]
        if not isinstance(exclusions, list):
            raise SidecarError("invalid_enrichment", "Enrichment field 'excludedRepetitions' must be an array.")
        extensions = draft.setdefault("extensions", {})
        if not isinstance(extensions, dict):
            raise SidecarError("invalid_enrichment", "Draft extensions must be an object.")
        if exclusions:
            extensions["excludedRepetitions"] = exclusions
        else:
            extensions.pop("excludedRepetitions", None)
        merged_keys.append(f"excludedRepetitions={len(exclusions)}")

    return merged_keys


def _infer_bilingual_path(draft_path: Path | None, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.expanduser()
    if draft_path is None:
        return None
    workdir = draft_path.expanduser().resolve().parent
    frozen = workdir / "bilingual-lyrics.frozen.json"
    return frozen if frozen.is_file() else (workdir / "bilingual-lyrics.json")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Calculate and verify Unicode code point spans for Schema v3 drafts."
    )
    parser.add_argument("draft", type=Path, nargs="?", help="Optional path to semantic-draft.json")
    parser.add_argument(
        "--bilingual",
        type=Path,
        help="Path to bilingual-lyrics(.frozen).json (default: auto-inferred from draft workdir)",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Update spans in semantic-draft.json directly",
    )
    parser.add_argument(
        "--merge-enrichment",
        type=Path,
        help="Optional enrichment.json (phrases, grammarNotes, relations, uncertainties) to merge before resolving spans",
    )
    parser.add_argument("--line", help="Query line by sourceOrder (int) or lineId (str)")
    parser.add_argument("--text", help="Query substring to find in the queried line")
    args = parser.parse_args()

    bilingual_path = _infer_bilingual_path(args.draft, args.bilingual)
    if bilingual_path is None:
        print("ERROR: pass either a draft path or --bilingual", file=sys.stderr)
        return 2

    try:
        bilingual = load_bilingual_lyrics(bilingual_path)
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 2

    lines_by_id = {line["lineId"]: line for line in bilingual.get("lines", [])}
    lines_by_order = {line["sourceOrder"]: line for line in bilingual.get("lines", [])}

    if args.line is not None:
        target_line = None
        if args.line.isdigit():
            target_line = lines_by_order.get(int(args.line))
        if target_line is None:
            target_line = lines_by_id.get(args.line)
        if target_line is None:
            print(f"ERROR: line '{args.line}' not found in bilingual lyrics", file=sys.stderr)
            return 1

        line_text = target_line["text"]
        print(f"lineId: {target_line['lineId']}")
        print(f"sourceOrder: {target_line['sourceOrder']}")
        print(f"lineText: {line_text}")
        print(f"codePoints: {len(line_text)}")

        if args.text:
            spans = resolve_line_span(line_text, args.text)
            if not spans:
                print(f"ERROR: '{args.text}' not found in line text", file=sys.stderr)
                return 1
            print(f"matches: {len(spans)}")
            for start, end in spans:
                segment = {
                    "lineId": target_line["lineId"],
                    "start": start,
                    "end": end,
                    "text": args.text,
                }
                print(json.dumps(segment, ensure_ascii=False))
        return 0

    if not args.draft:
        print("ERROR: either pass a draft file or use --line to query", file=sys.stderr)
        return 1

    draft_path = args.draft.expanduser()
    try:
        draft = read_json(draft_path)
        if args.merge_enrichment is not None:
            enrichment = read_json(args.merge_enrichment.expanduser())
            merged_keys = merge_enrichment_into_draft(draft, enrichment)
            print(f"Merged enrichment: {', '.join(merged_keys) if merged_keys else 'none'}")
        resolved, errors, messages = resolve_draft_spans(draft, bilingual)
        for msg in messages:
            print(msg)
        print(f"Summary: {resolved} span(s) resolved, {errors} error(s)")
        if args.in_place and errors == 0 and (resolved > 0 or args.merge_enrichment is not None):
            write_json_atomic(draft_path, draft, replace=True)
            print(f"updated: {draft_path}")
        return 1 if errors > 0 else 0
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
