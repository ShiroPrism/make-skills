#!/usr/bin/env python3
"""Condense Schema v3 semantic candidate review and emit semantic-audit templates.

Reads analysis-candidate.json and pairs lines directly with frozen
bilingual-lyrics.frozen.json by sourceOrder (zero timestamps).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sidecarlib import (
    AUDIT_VERSION,
    SEMANTIC_AUDIT_SCHEMA_ID,
    SidecarError,
    configure_utf8_stdio,
    load_bilingual_lyrics,
    read_json,
    sha256_file,
    write_json_atomic,
)
from v3lib import (
    load_frozen_candidate,
    read_candidate_hash,
)


def extract_translations_by_order(bilingual_path: Path) -> dict[int, str | None]:
    """Extract translations keyed strictly by 0-based sourceOrder."""
    if not bilingual_path.is_file():
        return {}
    bilingual = load_bilingual_lyrics(bilingual_path)
    return {line["sourceOrder"]: line.get("translation") for line in bilingual["lines"]}


def build_audit_summary(
    candidate: dict,
    candidate_hash: str,
    trans_by_order: dict[int, str | None],
    learner_language: str,
) -> tuple[str, dict]:
    """Generate concise textual summary and base audit report template without timestamps."""
    blocks = candidate.get("blocks", [])
    meaning_units = candidate.get("meaningUnits", [])
    lines = candidate.get("lines", [])
    phrases = candidate.get("phrases", [])
    notes = candidate.get("grammarNotes", [])

    line_by_id = {l["lineId"]: l for l in lines}

    mu_by_occurrence_id: dict[str, dict] = {}
    for mu in meaning_units:
        for occ in mu.get("occurrences", []):
            occ_id = occ.get("occurrenceId")
            if occ_id:
                mu_by_occurrence_id[occ_id] = mu

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
    content_hash = candidate.get("source", {}).get("contentHash", "unknown")
    out.append("=" * 72)
    out.append(f"SEMANTIC AUDIT SUMMARY (v3): {content_hash[:24]}...")
    out.append(f"Candidate SHA256: {candidate_hash}")
    out.append(
        f"Coverage: {len(lines)} lines | {len(blocks)} blocks | "
        f"{len(meaning_units)} meaning units | {len(phrases)} phrases | {len(notes)} notes"
    )
    out.append(f"Learner Language: {learner_language}")
    out.append("=" * 72)

    for idx, b in enumerate(blocks, 1):
        bid = b.get("blockId", f"b_{idx}")
        labels = [lbl.get("key") or lbl.get("name", "") for lbl in b.get("labels", [])]
        label_str = f" [{', '.join(filter(None, labels))}]" if labels else ""

        out.append(f"\n--- Block {bid}{label_str} ---")

        for lid in b.get("lineIds", []):
            line_obj = line_by_id.get(lid)
            if not line_obj:
                out.append(f"  [{lid}] (Unknown line)")
                continue
            s_order = line_obj.get("sourceOrder", -1)
            src_text = line_obj.get("text", "")
            if s_order in trans_by_order:
                raw_tr = trans_by_order[s_order]
                tr_text = raw_tr if (isinstance(raw_tr, str) and raw_tr.strip()) else "(Untranslated / filler)"
            else:
                tr_text = "(No frozen translation found)"
            out.append(f"  [{lid}] {line_obj.get('language', 'src').upper()}: {src_text}")
            out.append(f"          TR : {tr_text}")

            for p in phrases_by_block_line.get((bid, lid), []):
                surf = p.get("surface", "")
                gloss = p.get("gloss", "")
                expl = p.get("explanation", "")
                out.append(f"               phrase [{p.get('phraseId', '')}]: {surf} [{gloss}] — {expl}")

        b_parts = b.get("meaning", {}).get("parts", [])
        b_mus: list[dict] = []
        for p in b_parts:
            muo_id = p.get("meaningUnitOccurrenceId")
            mu = mu_by_occurrence_id.get(muo_id)
            if mu and mu not in b_mus:
                b_mus.append(mu)

        if not b_mus:
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
    excluded_reps = candidate.get("extensions", {}).get("excludedRepetitions", [])
    if isinstance(excluded_reps, list) and excluded_reps:
        out.append("EXCLUDED REPETITION CANDIDATES (audit each reason):")
        for item in excluded_reps:
            if isinstance(item, dict):
                out.append(f"  - {item.get('repetitionId', '')}: {item.get('reason', '')}")
        out.append("=" * 72)

    out.append("PRE-AUDIT DIAGNOSTICS:")
    uncovered_lines = [l["lineId"] for l in lines if not any(l["lineId"] in b.get("lineIds", []) for b in blocks)]
    if uncovered_lines:
        out.append(f"  [FAIL] Uncovered lines not in any block: {uncovered_lines}")
    else:
        out.append("  [PASS] All lines are monotonically mapped into blocks.")

    # Heuristic coverage check: warn if multi-line block MU text is suspiciously short vs combined line translations
    short_mu_warnings: list[str] = []
    for b in blocks:
        bid = b.get("blockId", "")
        b_lids = b.get("lineIds", [])
        if len(b_lids) < 2:
            continue
        tr_parts = []
        for lid in b_lids:
            line_obj = line_by_id.get(lid)
            if not line_obj:
                continue
            tr_val = trans_by_order.get(line_obj.get("sourceOrder", -1))
            if isinstance(tr_val, str) and tr_val.strip():
                tr_parts.append(tr_val.strip())
        if len(tr_parts) < 2:
            continue
        combined_tr_len = sum(len(t) for t in tr_parts)
        mu_texts = []
        for part in b.get("meaning", {}).get("parts", []):
            muo_id = part.get("meaningUnitOccurrenceId")
            mu = mu_by_occurrence_id.get(muo_id)
            if mu:
                override_text = None
                for occ in mu.get("occurrences", []):
                    if occ.get("occurrenceId") == muo_id:
                        ov = occ.get("semanticOverride")
                        if isinstance(ov, dict) and isinstance(ov.get("text"), str):
                            override_text = ov["text"]
                        break
                mu_texts.append(override_text or mu.get("text", ""))
        combined_mu_len = sum(len(t.strip()) for t in mu_texts)
        if combined_tr_len >= 16 and combined_mu_len < combined_tr_len * 0.45:
            short_mu_warnings.append(
                f"{bid} (MU {combined_mu_len} chars vs {len(tr_parts)} translated lines = {combined_tr_len} chars — verify no line was omitted)"
            )
    if short_mu_warnings:
        for warn in short_mu_warnings:
            out.append(f"  [WARN] Possible omitted line in block meaning: {warn}")
    else:
        out.append("  [PASS] No suspiciously short multi-line block meanings detected.")

    expected_block_ids = [b["blockId"] for b in blocks if "blockId" in b]
    expected_mu_ids = [mu["meaningUnitId"] for mu in meaning_units if "meaningUnitId" in mu]
    out.append(f"  [INFO] Expected reviewedBlockIds ({len(expected_block_ids)}): {expected_block_ids}")
    out.append(f"  [INFO] Expected reviewedMeaningUnitIds ({len(expected_mu_ids)}): {expected_mu_ids}")
    out.append("=" * 72)

    template = {
        "schema": SEMANTIC_AUDIT_SCHEMA_ID,
        "auditVersion": AUDIT_VERSION,
        "candidateSha256": candidate_hash,
        "learnerLanguage": learner_language,
        "status": "pending",
        "reviewedBlockIds": [],
        "reviewedMeaningUnitIds": [],
        "findings": [],
    }

    return "\n".join(out), template


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="Summarize Schema v3 candidate vs frozen bilingual lyrics and emit audit template."
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
        "--bilingual",
        type=Path,
        help="Path to bilingual-lyrics.frozen.json (default: auto-inferred from workdir)",
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

        if args.bilingual:
            bilingual_path = args.bilingual.expanduser().resolve()
        else:
            frozen = workdir / "bilingual-lyrics.frozen.json"
            bilingual_path = frozen if frozen.is_file() else (workdir / "bilingual-lyrics.json")
        trans_by_order = extract_translations_by_order(bilingual_path) if bilingual_path.is_file() else {}

        learner_lang = (
            args.learner_language
            or candidate.get("extensions", {}).get("learnerLanguage")
            or "zh-CN"
        )

        summary_text, template = build_audit_summary(
            candidate=candidate,
            candidate_hash=candidate_hash,
            trans_by_order=trans_by_order,
            learner_language=learner_lang,
        )

        print(summary_text)

        if args.emit_template:
            emit_path = (
                workdir / "semantic-audit.json"
                if args.emit_template == Path("default")
                else args.emit_template.expanduser().resolve()
            )
            if emit_path.is_file() and not args.replace:
                print(f"\n[NOTICE] Existing audit report found at {emit_path}. Preserved (use --replace to overwrite).")
            else:
                if emit_path.is_file():
                    try:
                        prev_doc = read_json(emit_path)
                    except SidecarError:
                        prev_doc = None
                    if isinstance(prev_doc, dict) and prev_doc.get("status") in ("pass", "fail"):
                        history_dir = workdir / "audit-history"
                        history_dir.mkdir(parents=True, exist_ok=True)
                        prev_hash = str(prev_doc.get("candidateSha256", "unknown"))
                        short_hash = prev_hash.split(":")[-1][:8] or "unknown"
                        round_num = len(list(history_dir.glob("semantic-audit-*.json"))) + 1
                        archive_path = history_dir / f"semantic-audit-r{round_num:02d}-{short_hash}.json"
                        write_json_atomic(archive_path, prev_doc, replace=True)
                        print(f"\n[ARCHIVED] Previous audit report saved to: {archive_path}")

                write_json_atomic(emit_path, template, replace=args.replace)
                validate_script = Path(__file__).resolve().parent / "validate_audit.py"
                print(f"\n[OK] Emitted pending semantic-audit template to: {emit_path}")
                print("     Inspect every block & meaningUnit above, then populate reviewedBlockIds,")
                print("     reviewedMeaningUnitIds, findings, and set status to 'pass' or 'fail'.")
                print("     Stage A (Audit Child self-check — before isolation proof):")
                print(
                    f'       python -X utf8 "{validate_script}" "{candidate_path}" '
                    f'--candidate-hash "{hash_path}" "{emit_path}" '
                    f'--learner-language "{learner_lang}" --check-format'
                )
                print("     Stage B (Orchestrator full gate — after record_isolation.py --stage semantic-audit):")
                print(
                    f'       python -X utf8 "{validate_script}" "{candidate_path}" '
                    f'--candidate-hash "{hash_path}" "{emit_path}" '
                    f'--learner-language "{learner_lang}" '
                    f'--bilingual "{bilingual_path}" '
                    f'--isolation "{workdir / "isolation-semantic-audit.json"}"'
                )

        return 0
    except SidecarError as exc:
        print(f"ERROR [{exc.code}] {exc.path}: {exc.message}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"ERROR [audit_summary_error]: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
