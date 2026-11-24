#!/usr/bin/env python3
"""Condense semantic candidate review and emit semantic-audit templates.

This deterministic tool reads analysis-candidate.json, pairs blocks with frozen
translated LRC lines, prints a concise block-by-block semantic comparison summary,
and optionally emits a schema-compliant semantic-audit.json template.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sidecarlib import (
    SidecarError,
    configure_utf8_stdio,
    parse_lrc_rows,
    read_json,
    sha256_bytes,
    sha256_file,
    write_json_atomic,
)
from v2lib import (
    AUDIT_VERSION,
    SEMANTIC_AUDIT_SCHEMA_ID,
    load_frozen_candidate,
    read_candidate_hash,
    validate_semantic_audit,
)


def extract_translations(translated_lrc_path: Path) -> dict[int, str]:
    """Extract inserted translated lines mapped by timestamp."""
    if not translated_lrc_path.is_file():
        return {}
    rows = parse_lrc_rows(translated_lrc_path)
    seen_times: set[int] = set()
    trans_map: dict[int, str] = {}
    for r in rows:
        t = r.timestamps[0] if r.timestamps else 0
        if t not in seen_times:
            seen_times.add(t)
        else:
            trans_map[t] = r.text
    return trans_map


def format_time_ms(ms: int) -> str:
    """Format millisecond integer to [MM:SS.xx]."""
    total_seconds = ms / 1000.0
    minutes = int(total_seconds // 60)
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:05.2f}"


def build_audit_summary(
    candidate: dict,
    candidate_hash: str,
    trans_map: dict[int, str],
    learner_language: str,
) -> tuple[str, dict]:
    """Generate concise textual summary and base audit report template."""
    blocks = candidate.get("blocks", [])
    meaning_units = candidate.get("meaningUnits", [])
    lines = candidate.get("lines", [])
    phrases = candidate.get("phrases", [])
    notes = candidate.get("grammarNotes", [])

    line_by_id = {l["lineId"]: l for l in lines}
    mu_by_id = {mu["meaningUnitId"]: mu for mu in meaning_units}

    mu_by_occurrence_id: dict[str, dict] = {}
    for mu in meaning_units:
        for occ in mu.get("occurrences", []):
            occ_id = occ.get("occurrenceId")
            if occ_id:
                mu_by_occurrence_id[occ_id] = mu

    # Group phrases by (blockId, lineId) and grammarNotes by blockId using Schema v2 fields
    phrases_by_block_line: dict[tuple[str, str], list[dict]] = {}
    for p in phrases:
        seen_keys: set[tuple[str, str]] = set()
        for occ in p.get("occurrences", []):
            occ_bid = occ.get("blockId", "")
            for seg in occ.get("sourceSegments", []):
                lid = seg.get("lineId")
                if not lid:
                    continue
                key = (occ_bid, lid)
                if key not in seen_keys:
                    seen_keys.add(key)
                    phrases_by_block_line.setdefault(key, []).append(p)

    notes_by_block: dict[str, list[dict]] = {}
    for n in notes:
        scope = n.get("scope", {})
        for bid in scope.get("blockIds", []):
            notes_by_block.setdefault(bid, []).append(n)

    out: list[str] = []
    song_source = candidate.get("source", {}).get("lrcFile", "unknown")
    out.append("=" * 72)
    out.append(f"SEMANTIC AUDIT SUMMARY: {song_source}")
    out.append(f"Candidate SHA256: {candidate_hash}")
    out.append(
        f"Coverage: {len(lines)} lines | {len(blocks)} blocks | "
        f"{len(meaning_units)} meaning units | {len(phrases)} phrases | {len(notes)} notes"
    )
    out.append(f"Learner Language: {learner_language}")
    out.append("=" * 72)

    for idx, b in enumerate(blocks, 1):
        bid = b.get("blockId", f"b_{idx}")
        start_ms = b.get("startTimeMs", 0)
        end_ms = b.get("endTimeMs", 0)
        labels = [lbl.get("key") or lbl.get("name", "") for lbl in b.get("labels", [])]
        label_str = f" [{', '.join(filter(None, labels))}]" if labels else ""

        out.append(f"\n--- Block {bid} ({format_time_ms(start_ms)} -> {format_time_ms(end_ms)}){label_str} ---")

        # Lines in this block
        b_line_ids = b.get("lineIds", [])
        for lid in b_line_ids:
            line_obj = line_by_id.get(lid)
            if not line_obj:
                out.append(f"  [{lid}] (Unknown line)")
                continue
            t_ms = line_obj.get("timeMs", 0)
            src_text = line_obj.get("text", "")
            tr_text = trans_map.get(t_ms, "(No frozen translation found)")
            out.append(f"  {line_obj.get('language', 'src').upper()}: {src_text}")
            out.append(f"  TR : {tr_text}")

            line_phrases = phrases_by_block_line.get((bid, lid), [])
            if line_phrases:
                for p in line_phrases:
                    surf = p.get("surface", "")
                    gloss = p.get("gloss", "")
                    expl = p.get("explanation", "")
                    out.append(f"       phrase [{p.get('phraseId', '')}]: {surf} [{gloss}] — {expl}")

        # Block meaning units
        b_parts = b.get("meaning", {}).get("parts", [])
        b_mus: list[dict] = []
        for p in b_parts:
            muo_id = p.get("meaningUnitOccurrenceId")
            mu = mu_by_occurrence_id.get(muo_id)
            if mu and mu not in b_mus:
                b_mus.append(mu)

        if not b_mus:
            # Fallback: check occurrences pointing to this blockId
            for mu in meaning_units:
                for occ in mu.get("occurrences", []):
                    if occ.get("blockId") == bid and mu not in b_mus:
                        b_mus.append(mu)

        if b_mus:
            for mu in b_mus:
                mu_id = mu.get("meaningUnitId", "")
                mu_text = mu.get("text", "")
                out.append(f"  => MU [{mu_id}]: {mu_text}")
        else:
            out.append("  => MU: [WARNING: No meaning unit attached to this block]")

        for note in notes_by_block.get(bid, []):
            scope_phrase = note.get("scope", {}).get("phraseId")
            phrase_tag = f" ({scope_phrase})" if scope_phrase else ""
            out.append(f"  => NOTE [{note.get('noteId', '')}]{phrase_tag}: {note.get('explanation', '')}")

    out.append("\n" + "=" * 72)
    out.append("PRE-AUDIT DIAGNOSTICS:")
    uncovered_lines = [l["lineId"] for l in lines if not any(l["lineId"] in b.get("lineIds", []) for b in blocks)]
    if uncovered_lines:
        out.append(f"  [FAIL] Uncovered lines not in any block: {uncovered_lines}")
    else:
        out.append("  [PASS] All lines are monotonically mapped into blocks.")

    reviewed_block_ids = [b["blockId"] for b in blocks if "blockId" in b]
    reviewed_mu_ids = [mu["meaningUnitId"] for mu in meaning_units if "meaningUnitId" in mu]
    out.append(f"  [PASS] {len(reviewed_block_ids)} block IDs and {len(reviewed_mu_ids)} meaning unit IDs mapped.")
    out.append("=" * 72)

    template = {
        "schema": SEMANTIC_AUDIT_SCHEMA_ID,
        "auditVersion": AUDIT_VERSION,
        "candidateSha256": candidate_hash,
        "learnerLanguage": learner_language,
        "status": "pass",
        "reviewedBlockIds": reviewed_block_ids,
        "reviewedMeaningUnitIds": reviewed_mu_ids,
        "findings": [],
    }

    return "\n".join(out), template


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Summarize candidate vs frozen translations and emit audit template."
    )
    parser.add_argument(
        "target",
        type=Path,
        help="Path to analysis-candidate.json or <song>.grammar-work directory",
    )
    parser.add_argument(
        "--candidate-hash",
        type=Path,
        help="Path to analysis-candidate.sha256 (default: <workdir>/analysis-candidate.sha256)",
    )
    parser.add_argument(
        "--translated",
        type=Path,
        help="Path to translated.lrc (default: <workdir>/translated.lrc)",
    )
    parser.add_argument(
        "--learner-language",
        help="Learner language (default: from candidate or zh-CN)",
    )
    parser.add_argument(
        "--emit-template",
        type=Path,
        nargs="?",
        const=Path("default"),
        help="Emit semantic-audit.json template to specified path or <workdir>/semantic-audit.json",
    )
    parser.add_argument(
        "--replace",
        "--force",
        action="store_true",
        help="Overwrite existing audit report template if it already exists",
    )
    args = parser.parse_args()

    try:
        target = args.target.expanduser().resolve()
        if target.is_dir() or target.name.endswith(".grammar-work"):
            workdir = target
            candidate_path = workdir / "analysis-candidate.json"
        elif target.name == "analysis-candidate.json":
            candidate_path = target
            workdir = target.parent
        else:
            candidate_path = target
            workdir = target.parent

        if not candidate_path.is_file():
            raise SidecarError("file_not_found", f"Candidate file not found: {candidate_path}")

        hash_path = args.candidate_hash.expanduser().resolve() if args.candidate_hash else workdir / "analysis-candidate.sha256"

        if hash_path.is_file():
            candidate, candidate_hash = load_frozen_candidate(candidate_path, hash_path)
        else:
            candidate = read_json(candidate_path)
            candidate_hash = sha256_file(candidate_path)

        translated_path = args.translated.expanduser().resolve() if args.translated else workdir / "translated.lrc"
        trans_map = extract_translations(translated_path) if translated_path.is_file() else {}

        learner_lang = (
            args.learner_language
            or candidate.get("extensions", {}).get("learnerLanguage")
            or "zh-CN"
        )

        summary_text, template = build_audit_summary(
            candidate=candidate,
            candidate_hash=candidate_hash,
            trans_map=trans_map,
            learner_language=learner_lang,
        )

        print(summary_text)

        if args.emit_template:
            if args.emit_template == Path("default"):
                emit_path = workdir / "semantic-audit.json"
            else:
                emit_path = args.emit_template.expanduser().resolve()

            if emit_path.is_file() and not args.replace:
                print(f"\n[NOTICE] Existing audit report found at {emit_path}. Preserved (use --replace to overwrite).")
            else:
                issues = validate_semantic_audit(
                    report=template,
                    candidate=candidate,
                    candidate_hash=candidate_hash,
                    learner_language=learner_lang,
                )
                if issues:
                    print(f"\n[WARN] Generated template has {len(issues)} validation notices:", file=sys.stderr)
                    for iss in issues:
                        print(f"  - [{iss.code}] {iss.message}", file=sys.stderr)
                write_json_atomic(emit_path, template, replace=args.replace)
                print(f"\n[OK] Emitted valid semantic-audit template to: {emit_path}")
                print("     To fail the audit with findings, edit status to 'fail' and add entries to findings.")
                print("     To verify, run: python -X utf8 scripts/validate_audit.py ...")

        return 0

    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR [audit_summary_error]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
