#!/usr/bin/env python3
"""Standard-library-only regression suite for the Schema v3 lyrics-grammar-sidecar skill."""

from __future__ import annotations

import atexit
import copy
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import unittest
from pathlib import Path
from typing import Any

from sidecarlib import (
    AUDIT_VERSION,
    BILINGUAL_SCHEMA_ID,
    BILINGUAL_VERSION,
    CONTENT_PROJECTION_VERSION,
    FINGERPRINT_VERSION,
    ISOLATION_METHODS,
    ISOLATION_STAGES,
    ISOLATION_VERSION,
    LINE_ID_VERSION,
    MANIFEST_SCHEMA_ID,
    MANIFEST_VERSION,
    MIN_REPETITION_CODE_POINTS,
    REPETITION_CANDIDATE_VERSION,
    SCHEMA_VERSION,
    SEMANTIC_AUDIT_SCHEMA_ID,
    SIDECAR_SCHEMA_ID,
    SidecarError,
    configure_utf8_stdio,
    extract_bilingual_from_bilingual_lrc,
    extract_bilingual_from_lrc_and_tmp,
    grammar_line_fingerprint,
    grammar_line_id,
    load_bilingual_lyrics,
    pretty_json,
    read_json,
    sha256_file,
    validate_bilingual_lyrics,
    validate_manifest,
    validate_schema_instance,
    verify_frozen_bilingual,
    write_accepted_bilingual,
    write_json_atomic,
)
from v3lib import (
    AUDIT_FINDING_CODES,
    build_isolation_proof_v3,
    candidate_groups,
    discover_repetition_candidates,
    finalize_sidecar_v3,
    load_frozen_candidate,
    load_v3_schema,
    normalized_analysis_candidate,
    prepare_semantic_candidate,
    validate_distinct_children,
    validate_finalized_sidecar_v3,
    validate_grammar_analysis_v3,
    validate_isolation_proof_v3,
    validate_repetition_completion,
    validate_semantic_audit,
)

SKILL_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = SKILL_ROOT / "fixtures"
GOLDEN_VECTORS = read_json(FIXTURES / "golden-vectors.json")
REPETITION_DIR = FIXTURES / "repetition"
REPETITION_BLOCK_IDS = ("b_repeat1", "b_repeat2", "b_repeat3")

_LRC_FIXTURE_STAGE = tempfile.TemporaryDirectory(
    prefix="lyrics-grammar-v3-fixtures-"
)
_LRC_FIXTURE_ROOT = Path(_LRC_FIXTURE_STAGE.name)
atexit.register(_LRC_FIXTURE_STAGE.cleanup)


def staged_fixture_lrc(path: Path) -> Path:
    """Materialize a committed .txt LRC fixture as a temporary .lrc file."""
    relative = path.relative_to(FIXTURES)
    if relative.suffix != ".txt":
        raise ValueError(f"Not an LRC text fixture: {path}")
    staged = _LRC_FIXTURE_ROOT / relative.with_suffix(".lrc")
    staged.parent.mkdir(parents=True, exist_ok=True)
    if not staged.exists():
        staged.write_bytes(path.read_bytes())
    return staged


JA_SOURCE_LRC = staged_fixture_lrc(FIXTURES / "ja" / "source.txt")
JA_TRANSLATED_LRC = staged_fixture_lrc(FIXTURES / "ja" / "translated.txt")
EN_TRANSLATED_LRC = staged_fixture_lrc(FIXTURES / "en" / "translated.txt")
KO_TRANSLATED_LRC = staged_fixture_lrc(FIXTURES / "ko" / "translated.txt")
ZH_TRANSLATED_LRC = staged_fixture_lrc(FIXTURES / "zh" / "translated.txt")
EDGE_TRANSLATED_LRC = staged_fixture_lrc(FIXTURES / "edge" / "translated.txt")


def labels(namespace: str, key: str) -> list[dict[str, str]]:
    return [{"namespace": namespace, "key": key}]


def line_map(bilingual: dict) -> dict[str, dict]:
    return {line["lineId"]: line for line in bilingual["lines"]}


def draft_line(line: dict, language: str) -> dict:
    return {
        "lineId": line["lineId"],
        "sourceOrder": line["sourceOrder"],
        "text": line["text"],
        "fingerprint": line["fingerprint"],
        "role": "text",
        "language": language,
    }


def segment(line: dict, start: int | None = None, end: int | None = None) -> dict:
    actual_start = 0 if start is None else start
    actual_end = len(line["text"]) if end is None else end
    return {
        "lineId": line["lineId"],
        "start": actual_start,
        "end": actual_end,
        "text": line["text"][actual_start:actual_end],
    }


def source_object(bilingual: dict, source_languages: list[str]) -> dict:
    return {
        "sourceLanguages": source_languages,
        "lineCount": bilingual["lineCount"],
        "contentHash": bilingual["contentHash"],
    }


def block_object(
    block_id: str,
    block_lines: list[dict],
    part_ids: list[str],
    *,
    text_before: dict[int, str] | None = None,
) -> dict:
    parts = []
    for index, occurrence_id in enumerate(part_ids):
        part: dict[str, Any] = {"meaningUnitOccurrenceId": occurrence_id}
        if text_before and index in text_before:
            part["textBefore"] = text_before[index]
        parts.append(part)
    return {
        "blockId": block_id,
        "lineIds": [line["lineId"] for line in block_lines],
        "meaning": {"parts": parts},
        "labels": [],
        "confidence": 0.92,
    }


def meaning_unit(
    unit_id: str,
    text: str,
    occurrences: list[dict],
) -> dict:
    return {
        "meaningUnitId": unit_id,
        "text": text,
        "labels": [],
        "confidence": 0.9,
        "occurrences": occurrences,
    }


def meaning_occurrence(
    occurrence_id: str,
    block_id: str,
    segments: list[dict],
    *,
    override_text: str | None = None,
    reason: str = "语境变化需要单独表达。",
) -> dict:
    occurrence: dict[str, Any] = {
        "occurrenceId": occurrence_id,
        "blockId": block_id,
        "sourceSegments": segments,
    }
    if override_text is not None:
        occurrence["semanticOverride"] = {
            "reason": reason,
            "text": override_text,
        }
    return occurrence


def phrase_object(
    phrase_id: str,
    surface: str,
    occurrences: list[dict],
    *,
    explanation: str = "共享短语的规范语法解释。",
    gloss: str = "共享短语释义",
    role: str = "shared_phrase",
) -> dict:
    return {
        "phraseId": phrase_id,
        "kind": "phrase",
        "surface": surface,
        "role": role,
        "labels": labels("syntax", "shared_occurrence"),
        "explanation": explanation,
        "gloss": gloss,
        "confidence": 0.9,
        "occurrences": occurrences,
    }


def phrase_occurrence(
    occurrence_id: str,
    block_id: str,
    segments: list[dict],
    *,
    override: dict | None = None,
) -> dict:
    occurrence: dict[str, Any] = {
        "occurrenceId": occurrence_id,
        "blockId": block_id,
        "sourceSegments": segments,
    }
    if override is not None:
        occurrence["semanticOverride"] = override
    return occurrence


def base_document(
    bilingual: dict,
    lines: list[dict],
    blocks: list[dict],
    meaning_units: list[dict],
    phrases: list[dict],
    *,
    learner_language: str,
    source_languages: list[str],
    repetition_groups: list[dict] | None = None,
    relations: list[dict] | None = None,
    notes: list[dict] | None = None,
    uncertainties: list[dict] | None = None,
) -> dict:
    return {
        "schema": SIDECAR_SCHEMA_ID,
        "schemaVersion": SCHEMA_VERSION,
        "source": source_object(bilingual, source_languages),
        "lines": lines,
        "repetitionGroups": repetition_groups or [],
        "meaningUnits": meaning_units,
        "blocks": blocks,
        "phrases": phrases,
        "relations": relations or [],
        "grammarNotes": notes or [],
        "uncertainties": uncertainties or [],
        "extensions": {"learnerLanguage": learner_language},
    }


def simple_document(
    bilingual: dict,
    *,
    source_language: str,
    learner_language: str,
    meaning_text: str,
    explanation: str,
    gloss: str,
) -> dict:
    lines = [draft_line(line, source_language) for line in bilingual["lines"]]
    block_id = "b_fixture"
    unit_id = "mu_fixture"
    occurrence_id = "muo_fixture"
    phrase_id = "p_fixture"
    phrase_occ_id = "po_fixture"
    block_segments = [segment(line) for line in bilingual["lines"]]
    units = [
        meaning_unit(
            unit_id,
            meaning_text,
            [meaning_occurrence(occurrence_id, block_id, block_segments)],
        )
    ]
    blocks = [block_object(block_id, bilingual["lines"], [occurrence_id])]
    phrase = phrase_object(
        phrase_id,
        "".join(line["text"] for line in bilingual["lines"]),
        [phrase_occurrence(phrase_occ_id, block_id, block_segments)],
        explanation=explanation,
        gloss=gloss,
    )
    notes = [
        {
            "noteId": "g_fixture",
            "scope": {"blockIds": [block_id], "phraseId": phrase_id},
            "explanation": explanation,
            "labels": labels("syntax", "fixture"),
            "confidence": 0.8,
        }
    ]
    return base_document(
        bilingual,
        lines,
        blocks,
        units,
        [phrase],
        learner_language=learner_language,
        source_languages=[source_language],
        notes=notes,
    )


def two_block_repeat_document(
    bilingual: dict,
    *,
    learner_language: str = "zh-CN",
) -> dict:
    b_lines = bilingual["lines"]
    lines = [draft_line(line, "ja") for line in b_lines]
    block_a = "b_block_a"
    block_b = "b_block_b"
    segs_a = [segment(b_lines[0])]
    segs_b = [segment(b_lines[2])]
    units = [
        meaning_unit(
            "mu_shared_lead",
            "第一层共现意译。",
            [
                meaning_occurrence("muo_lead_a", block_a, [segment(b_lines[0])]),
                meaning_occurrence("muo_lead_b", block_b, [segment(b_lines[2])]),
            ],
        ),
        meaning_unit(
            "mu_tail",
            "尾句意译。",
            [
                meaning_occurrence("muo_tail_a", block_a, [segment(b_lines[1])]),
                meaning_occurrence("muo_tail_b", block_b, [segment(b_lines[3])]),
            ],
        ),
    ]
    blocks = [
        block_object(block_a, b_lines[0:2], ["muo_lead_a", "muo_tail_a"]),
        block_object(block_b, b_lines[2:4], ["muo_lead_b", "muo_tail_b"]),
    ]
    phrases = [
        phrase_object(
            "p_shared_lead",
            b_lines[0]["text"],
            [
                phrase_occurrence("po_lead_a", block_a, segs_a),
                phrase_occurrence("po_lead_b", block_b, segs_b),
            ],
        )
    ]
    doc = base_document(
        bilingual,
        lines,
        blocks,
        units,
        phrases,
        learner_language=learner_language,
        source_languages=["ja"],
        notes=[
            {
                "noteId": "g_shared_lead",
                "scope": {"blockIds": [block_a, block_b], "phraseId": "p_shared_lead"},
                "explanation": "两处共同使用同一个短语实例。",
                "labels": labels("syntax", "shared_note"),
                "confidence": 0.9,
            }
        ],
    )
    doc["repetitionGroups"] = candidate_groups(discover_repetition_candidates(doc, bilingual))
    return doc


def make_bilingual_from_lrc_lines(raw_rows: list[tuple[str, str | None]], source_languages: list[str] | None = None, learner_language: str = "zh-CN") -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        lrc_path = Path(tmp) / "synthetic.lrc"
        lines_out = []
        for idx, (src, trans) in enumerate(raw_rows):
            ts = f"[00:{idx + 1:02d}.00]"
            lines_out.append(f"{ts}{src}")
            if trans is not None:
                lines_out.append(f"{ts}{trans}")
        lrc_path.write_text("\n".join(lines_out) + "\n", encoding="utf-8", newline="\n")
        return extract_bilingual_from_bilingual_lrc(
            lrc_path,
            source_languages=source_languages,
            learner_language=learner_language,
        )


def stage_repetition_fixture(base: Path) -> dict[str, Any]:
    work = base / "repetition.grammar-work"
    work.mkdir(parents=True, exist_ok=True)
    bilingual = read_json(REPETITION_DIR / "bilingual-lyrics.json")
    bilingual_path = work / "bilingual-lyrics.json"
    write_json_atomic(bilingual_path, bilingual, replace=True)
    manifest = write_accepted_bilingual(bilingual_path, work)
    draft = read_json(REPETITION_DIR / "semantic-draft.json")
    candidates = discover_repetition_candidates(draft, bilingual)
    draft_path = work / "semantic-draft.json"
    candidates_path = work / "repetition-candidates.json"
    write_json_atomic(draft_path, draft, replace=True)
    write_json_atomic(candidates_path, candidates, replace=True)
    frozen_path = work / "bilingual-lyrics.frozen.json"
    manifest_path = work / "translation-manifest.json"
    return {
        "work": work,
        "bilingual": bilingual,
        "bilingual_path": bilingual_path,
        "frozen_path": frozen_path,
        "manifest": manifest,
        "manifest_path": manifest_path,
        "draft": draft,
        "draft_path": draft_path,
        "candidates": candidates,
        "candidates_path": candidates_path,
        "grammar_iso_path": work / "isolation-grammar-analysis.json",
        "audit_iso_path": work / "isolation-semantic-audit.json",
        "candidate_path": work / "analysis-candidate.json",
        "candidate_hash_path": work / "analysis-candidate.sha256",
        "audit_path": work / "semantic-audit.json",
        "output_path": base / "repetition.json",
    }


def build_repetition_ready_chain(base: Path) -> dict[str, Any]:
    state = stage_repetition_fixture(base)
    grammar_iso = build_isolation_proof_v3(
        state["bilingual"],
        "grammar-analysis",
        state["draft_path"],
        "native-subagent",
        child_transcript_id="child-grammar",
        parent_transcript_id="parent-session",
    )
    write_json_atomic(state["grammar_iso_path"], grammar_iso, replace=True)
    candidate, prep_report = prepare_semantic_candidate(
        state["work"],
        state["draft_path"],
        learner_language="zh-CN",
        frozen_bilingual_path=state["frozen_path"],
        manifest_path=state["manifest_path"],
        candidate_path=state["candidate_path"],
        candidate_hash_path=state["candidate_hash_path"],
        repetition_candidates_path=state["candidates_path"],
    )
    candidate_hash = prep_report["candidateHash"]
    audit_doc = {
        "schema": SEMANTIC_AUDIT_SCHEMA_ID,
        "auditVersion": AUDIT_VERSION,
        "candidateSha256": candidate_hash,
        "learnerLanguage": "zh-CN",
        "status": "pass",
        "reviewedBlockIds": list(REPETITION_BLOCK_IDS),
        "reviewedMeaningUnitIds": [
            unit["meaningUnitId"] for unit in candidate["meaningUnits"]
        ],
        "findings": [],
    }
    write_json_atomic(state["audit_path"], audit_doc, replace=True)
    audit_iso = build_isolation_proof_v3(
        state["bilingual"],
        "semantic-audit",
        state["audit_path"],
        "native-subagent",
        child_transcript_id="child-audit",
        parent_transcript_id="parent-session",
    )
    write_json_atomic(state["audit_iso_path"], audit_iso, replace=True)
    state["candidate"] = candidate
    state["candidate_hash"] = candidate_hash
    state["grammar_iso"] = grammar_iso
    state["audit"] = audit_doc
    state["audit_iso"] = audit_iso
    return state


def issue_codes(issues) -> list[str]:
    return [issue.code for issue in issues]


class GrammarSidecarV3Test(unittest.TestCase):
    maxDiff = None

    def assert_issue(self, issues, expected_code: str) -> None:
        self.assertIn(expected_code, issue_codes(issues), issues)

    def run_cli(
        self, *args: str, cwd: Path | None = None
    ) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            [sys.executable, *args],
            cwd=str(cwd or SKILL_ROOT),
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        if result.returncode != 0:
            self.fail(
                f"Command failed ({result.returncode}): {args}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
            )
        return result

    def test_six_fixtures_are_valid_v3(self) -> None:
        for name in ("edge", "en", "ja", "ko", "zh", "repetition"):
            sidecar_path = FIXTURES / name / "sidecar.json"
            bilingual_path = FIXTURES / name / "bilingual-lyrics.json"
            self.assertTrue(sidecar_path.is_file(), name)
            self.assertTrue(bilingual_path.is_file(), name)
            self.assertFalse((FIXTURES / name / "source-projection.json").exists(), name)
            sidecar = read_json(sidecar_path)
            bilingual = read_json(bilingual_path)
            self.assertEqual(sidecar["schemaVersion"], 3, name)
            self.assertEqual(bilingual["schema"], BILINGUAL_SCHEMA_ID, name)
            self.assertEqual(bilingual["schemaVersion"], BILINGUAL_VERSION, name)
            self.assertNotIn("lrcFile", sidecar["source"], name)
            self.assertNotIn("songId", sidecar["source"], name)
            self.assertNotIn("lrcProjectionHash", sidecar["source"], name)
            for line in sidecar["lines"]:
                self.assertRegex(line["lineId"], r"^l_\d{3,}$", name)
                self.assertNotIn("timeMs", line, name)
            for block in sidecar["blocks"]:
                self.assertNotIn("startTimeMs", block, name)
                self.assertNotIn("endTimeMs", block, name)
            self.assertEqual(
                [],
                validate_grammar_analysis_v3(
                    sidecar, bilingual, learner_language="zh-CN"
                ),
                name,
            )

    def test_edge_fixture_uses_code_point_spans(self) -> None:
        sidecar = read_json(FIXTURES / "edge" / "sidecar.json")
        bilingual = read_json(FIXTURES / "edge" / "bilingual-lyrics.json")
        self.assertEqual(sidecar["source"]["sourceLanguages"], ["en", "ja"])
        first_line = sidecar["lines"][0]
        self.assertEqual(first_line["lineId"], "l_001")
        self.assertEqual(first_line["text"], "\U0001f600e\u0301")
        self.assertEqual(first_line["languageSpans"][1], {"start": 1, "end": 2, "language": "en"})
        self.assertEqual(
            [],
            validate_grammar_analysis_v3(sidecar, bilingual, learner_language="zh-CN"),
        )

    def test_v3_schemas_exist_and_v2_dir_absent(self) -> None:
        self.assertFalse((SKILL_ROOT / "schema" / "v2").exists())
        for filename in (
            "lyrics-grammar-analysis.schema.json",
            "bilingual-lyrics.schema.json",
            "isolation-proof.schema.json",
            "repetition-candidates.schema.json",
            "semantic-audit.schema.json",
        ):
            schema = load_v3_schema(filename)
            self.assertIn("$schema", schema, filename)

    def test_cross_repository_golden_vectors(self) -> None:
        contracts = GOLDEN_VECTORS["contractVersions"]
        self.assertEqual(contracts["projection"], CONTENT_PROJECTION_VERSION)
        self.assertEqual(contracts["lineId"], LINE_ID_VERSION)
        self.assertEqual(contracts["fingerprint"], FINGERPRINT_VERSION)
        self.assertEqual(contracts["sidecar"], SCHEMA_VERSION)
        self.assertEqual(contracts["isolation"], ISOLATION_VERSION)
        self.assertEqual(contracts["semanticAudit"], AUDIT_VERSION)
        self.assertEqual(contracts["repetitionCandidates"], REPETITION_CANDIDATE_VERSION)
        self.assertEqual(contracts["bilingualLyrics"], BILINGUAL_VERSION)
        self.assertEqual(contracts["manifest"], MANIFEST_VERSION)
        self.assertEqual(contracts["minimumRepetitionCodePoints"], MIN_REPETITION_CODE_POINTS)

        with tempfile.TemporaryDirectory() as tmp:
            for item in GOLDEN_VECTORS["fixtures"]:
                lrc_path = Path(tmp) / f"{item['name']}.lrc"
                lrc_path.write_text(item["lrc"], encoding="utf-8", newline="\n")
                bilingual = extract_bilingual_from_bilingual_lrc(
                    lrc_path,
                    title_hint=item.get("titleHint"),
                )
                self.assertEqual(bilingual["contentHash"], item["contentHash"], item["name"])
                self.assertEqual(len(bilingual["lines"]), len(item["lines"]), item["name"])
                for actual, expected in zip(bilingual["lines"], item["lines"]):
                    self.assertEqual(actual["lineId"], expected["lineId"], item["name"])
                    self.assertEqual(actual["text"], expected["text"], item["name"])
                    self.assertEqual(actual["fingerprint"], expected["fingerprint"], item["name"])

    def test_committed_invalid_fixtures_are_rejected(self) -> None:
        ja_bilingual = read_json(FIXTURES / "ja" / "bilingual-lyrics.json")
        html_doc = read_json(FIXTURES / "invalid" / "html-text.json")
        ref_doc = read_json(FIXTURES / "invalid" / "invalid-references.json")
        v2_doc = read_json(FIXTURES / "invalid" / "v2-rejected.json")
        v1_doc = read_json(FIXTURES / "invalid" / "v1-rejected.json")

        self.assert_issue(
            validate_grammar_analysis_v3(html_doc, ja_bilingual, learner_language="zh-CN"),
            "html_content",
        )
        self.assert_issue(
            validate_grammar_analysis_v3(ref_doc, ja_bilingual, learner_language="zh-CN"),
            "unresolved_block",
        )
        self.assert_issue(
            validate_grammar_analysis_v3(v2_doc, ja_bilingual, learner_language="zh-CN"),
            "unsupported_schema_version",
        )
        self.assert_issue(
            validate_grammar_analysis_v3(v1_doc, ja_bilingual, learner_language="zh-CN"),
            "unsupported_schema_version",
        )

    def test_extract_bilingual_lrc_and_tmp_filters_and_preserves_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            lrc = base / "Test Song - Test Singer.lrc"
            lrc.write_text(
                "\n".join(
                    [
                        "[ti:Test Song]",
                        "[00:01.00]Test Song - Test Singer",
                        "[00:02.00]作词：Someone",
                        "[00:05.00]光の中へ",
                        "[00:08.00]Ah〜",
                        "[00:10.00]光の中へ",
                    ]
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            tmp_txt = base / "Test Song - Test Singer.lrc.tmp.txt"
            tmp_txt.write_text(
                "\n".join(
                    [
                        "[ti:Test Song]",
                        "Test Song - Test Singer",
                        "作词：Someone",
                        "光の中へ",
                        "走进光芒之中",
                        "Ah〜",
                        "光の中へ",
                        "再次走向光里",
                    ]
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            doc = extract_bilingual_from_lrc_and_tmp(
                lrc,
                tmp_txt,
                source_languages=["ja"],
                learner_language="zh-CN",
            )
            self.assertEqual(doc["lineCount"], 3)
            self.assertEqual([l["lineId"] for l in doc["lines"]], ["l_001", "l_002", "l_003"])
            self.assertEqual([l["text"] for l in doc["lines"]], ["光の中へ", "Ah〜", "光の中へ"])
            self.assertEqual([l["translation"] for l in doc["lines"]], ["走进光芒之中", None, "再次走向光里"])
            self.assertEqual([], validate_bilingual_lyrics(doc))
            for forbidden in ("timeMs", "startTimeMs", "endTimeMs", "lrcFile", "songId"):
                self.assertNotIn(forbidden, json.dumps(doc))

    def test_json_reader_rejects_ambiguous_or_nonstandard_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dup_path = Path(tmp) / "dup.json"
            dup_path.write_text('{"a": 1, "a": 2}', encoding="utf-8")
            with self.assertRaises(SidecarError):
                read_json(dup_path)

            nan_path = Path(tmp) / "nan.json"
            nan_path.write_text('{"a": NaN}', encoding="utf-8")
            with self.assertRaises(SidecarError):
                read_json(nan_path)

    def test_exact_repetition_and_metadata_exclusion(self) -> None:
        bilingual = make_bilingual_from_lrc_lines(
            [
                ("夜明けの歌を君と歌う", "与你同唱"),
                ("新しい朝だ", "新的一天"),
                ("夜明けの歌を", "黎明之歌"),
                ("君と歌うよ", "与你同唱啊"),
            ]
        )
        b_lines = bilingual["lines"]
        lines = [draft_line(l, "ja") for l in b_lines]
        doc = base_document(
            bilingual,
            lines,
            [
                block_object("b_a", b_lines[0:2], ["muo_a"]),
                block_object("b_b", b_lines[2:4], ["muo_b"]),
            ],
            [
                meaning_unit("mu_a", "第一段。", [meaning_occurrence("muo_a", "b_a", [segment(b_lines[0]), segment(b_lines[1])])]),
                meaning_unit("mu_b", "第二段。", [meaning_occurrence("muo_b", "b_b", [segment(b_lines[2]), segment(b_lines[3])])]),
            ],
            [
                phrase_object("p_1", b_lines[0]["text"], [phrase_occurrence("po_1", "b_a", [segment(b_lines[0])])]),
            ],
            learner_language="zh-CN",
            source_languages=["ja"],
        )
        cands = discover_repetition_candidates(doc, bilingual)["candidates"]
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0]["normalizedText"], "夜明けの歌を君と歌う")
        self.assertEqual(len(cands[0]["occurrences"][1]["sourceSegments"]), 2)

    def test_repetition_completion_and_shared_semantic_rules(self) -> None:
        bilingual = read_json(FIXTURES / "repetition" / "bilingual-lyrics.json")
        sidecar = read_json(FIXTURES / "repetition" / "sidecar.json")
        self.assertEqual([], validate_grammar_analysis_v3(sidecar, bilingual, learner_language="zh-CN"))

        missing_grp = copy.deepcopy(sidecar)
        missing_grp["repetitionGroups"] = []
        _, rep_issues = validate_repetition_completion(missing_grp, bilingual)
        self.assert_issue(rep_issues, "missing_repetition_candidate")

        # Drift without override fails
        drift_doc = copy.deepcopy(sidecar)
        mu = next(u for u in drift_doc["meaningUnits"] if u["meaningUnitId"] == "mu_shared_core")
        mu["occurrences"][1]["sourceSegments"][0]["text"] = "違うテキスト"
        self.assert_issue(
            validate_grammar_analysis_v3(drift_doc, bilingual, learner_language="zh-CN"),
            "shared-occurrence-incomplete",
        )

        # Duplicate boundary punctuation fails
        punct_doc = copy.deepcopy(sidecar)
        punct_doc["blocks"][1]["meaning"]["parts"][2]["textBefore"] = "，"
        # Inject comma at end of previous meaning unit text to trigger boundary dup
        prev_occ_id = punct_doc["blocks"][1]["meaning"]["parts"][1]["meaningUnitOccurrenceId"]
        for u in punct_doc["meaningUnits"]:
            for occ in u["occurrences"]:
                if occ["occurrenceId"] == prev_occ_id:
                    u["text"] = u["text"].rstrip("。") + "，"
        self.assert_issue(
            validate_grammar_analysis_v3(punct_doc, bilingual, learner_language="zh-CN"),
            "duplicate_boundary_punctuation",
        )

    def test_override_requires_reason_and_multi_block_scope(self) -> None:
        bilingual = make_bilingual_from_lrc_lines(
            [
                ("夜明けの歌を君と歌う", "同唱黎明之歌"),
                ("終わらない夢", "无尽之梦"),
                ("夜明けの歌を君と歌う", "再次同唱"),
                ("新しい風", "崭新微风"),
            ]
        )
        doc = two_block_repeat_document(bilingual)
        doc["meaningUnits"][0]["occurrences"][1]["semanticOverride"] = {"reason": "  ", "text": "再次"}
        self.assert_issue(
            validate_grammar_analysis_v3(doc, bilingual, learner_language="zh-CN"),
            "empty_override_reason",
        )

    def test_semantic_audit_and_isolation_v3(self) -> None:
        bilingual = read_json(FIXTURES / "ja" / "bilingual-lyrics.json")
        sidecar = read_json(FIXTURES / "ja" / "sidecar.json")
        candidate_hash = "sha256:" + "a" * 64
        audit = {
            "schema": SEMANTIC_AUDIT_SCHEMA_ID,
            "auditVersion": AUDIT_VERSION,
            "candidateSha256": candidate_hash,
            "learnerLanguage": "zh-CN",
            "status": "pass",
            "reviewedBlockIds": ["b_fixture"],
            "reviewedMeaningUnitIds": ["mu_fixture"],
            "findings": [],
        }
        self.assertEqual([], validate_semantic_audit(audit, sidecar, candidate_hash, "zh-CN"))

        bad_audit = copy.deepcopy(audit)
        bad_audit["reviewedMeaningUnitIds"] = []
        self.assert_issue(
            validate_semantic_audit(bad_audit, sidecar, candidate_hash, "zh-CN"),
            "audit_review_coverage",
        )

        with tempfile.TemporaryDirectory() as tmp:
            draft_p = Path(tmp) / "draft.json"
            audit_p = Path(tmp) / "audit.json"
            write_json_atomic(draft_p, {"draft": True})
            write_json_atomic(audit_p, {"audit": True})
            iso_g = build_isolation_proof_v3(
                bilingual,
                "grammar-analysis",
                draft_p,
                "native-subagent",
                child_transcript_id="child-1",
                parent_transcript_id="parent",
            )
            iso_a = build_isolation_proof_v3(
                bilingual,
                "semantic-audit",
                audit_p,
                "native-subagent",
                child_transcript_id="child-2",
                parent_transcript_id="parent",
            )
            self.assertEqual(iso_g["isolationVersion"], 3)
            self.assertEqual([], validate_isolation_proof_v3(iso_g, bilingual, stage="grammar-analysis", artifact_path=draft_p))
            iso_a["childTranscriptId"] = "child-1"
            self.assert_issue(validate_distinct_children(iso_g, iso_a), "same_child_self_audit")

    def test_full_repetition_frozen_pipeline_and_tamper_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            state = build_repetition_ready_chain(base)
            out_path, written = finalize_sidecar_v3(
                state["output_path"],
                state["work"],
                learner_language="zh-CN",
                frozen_bilingual_path=state["frozen_path"],
                manifest_path=state["manifest_path"],
                draft_path=state["draft_path"],
                candidate_path=state["candidate_path"],
                candidate_hash_path=state["candidate_hash_path"],
                audit_path=state["audit_path"],
                grammar_proof_path=state["grammar_iso_path"],
                audit_proof_path=state["audit_iso_path"],
            )
            self.assertTrue(written)
            finalized = read_json(out_path)
            self.assertEqual(finalized["schemaVersion"], 3)
            self.assertNotIn("lrcFile", finalized["source"])
            self.assertNotIn("songId", finalized["source"])
            self.assertEqual(
                [],
                validate_finalized_sidecar_v3(
                    out_path,
                    state["work"],
                    "zh-CN",
                    frozen_bilingual_path=state["frozen_path"],
                ),
            )

            # Tamper frozen bilingual translation fails closed
            frozen = read_json(state["frozen_path"])
            frozen["lines"][0]["translation"] = "篡改译文"
            write_json_atomic(state["frozen_path"], frozen, replace=True)
            with self.assertRaises(SidecarError) as ctx:
                finalize_sidecar_v3(
                    state["output_path"],
                    state["work"],
                    learner_language="zh-CN",
                    frozen_bilingual_path=state["frozen_path"],
                    manifest_path=state["manifest_path"],
                    draft_path=state["draft_path"],
                    candidate_path=state["candidate_path"],
                    candidate_hash_path=state["candidate_hash_path"],
                    audit_path=state["audit_path"],
                    grammar_proof_path=state["grammar_iso_path"],
                    audit_proof_path=state["audit_iso_path"],
                    replace=True,
                )
            self.assertEqual(ctx.exception.code, "translation_changed_after_freeze")

    def test_emit_index_and_lrc_merge_occurrence_order(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        translator_scripts = SKILL_ROOT.parent / "lyrics-translator" / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            lrc = base / "Repeat Song - Singer.lrc"
            lrc.write_text(
                "\n".join(
                    [
                        "[ti:Repeat Song]",
                        "[00:01.00]Repeat Song - Singer",
                        "[00:02.00]词：Author",
                        "[00:05.00]光の中へ",
                        "[00:08.00]La la la",
                        "[00:12.00]光の中へ",
                    ]
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            work = base / "Repeat Song - Singer.grammar-work"
            self.run_cli(str(scripts / "extract_bilingual.py"), str(lrc), "--emit-index")
            idx_text = (work / "lyric-index.txt").read_text(encoding="utf-8").splitlines()
            self.assertEqual(idx_text, ["l_001 | 光の中へ", "l_002 | La la la", "l_003 | 光の中へ"])

            tmp_txt = base / "Repeat Song - Singer.lrc.tmp.txt"
            tmp_txt.write_text(
                "\n".join(
                    [
                        "[ti:Repeat Song]",
                        "Repeat Song - Singer",
                        "词：Author",
                        "光の中へ",
                        "第一次走进光芒",
                        "La la la",
                        "光の中へ",
                        "第二次迈向光明",
                    ]
                )
                + "\n",
                encoding="utf-8",
                newline="\n",
            )
            self.run_cli(str(scripts / "extract_bilingual.py"), str(lrc), "--learner-language", "zh-CN")
            bi = read_json(work / "bilingual-lyrics.json")
            self.assertEqual(
                [l["translation"] for l in bi["lines"]],
                ["第一次走进光芒", None, "第二次迈向光明"],
            )
            self.run_cli(str(translator_scripts / "lrc_merge.py"), str(lrc), str(tmp_txt))
            merged = lrc.read_text(encoding="utf-8").splitlines()
            self.assertIn("[00:05.00]第一次走进光芒", merged)
            self.assertIn("[00:12.00]第二次迈向光明", merged)

    def test_enrichment_blocks_and_repetition_boundary_and_exclusion(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        # 1. 1-char stray cross-line bleed is trimmed cleanly (e.g. trailing '青' on next line)
        bilingual = make_bilingual_from_lrc_lines(
            [
                ("考えたってわからないし", "怎么想都想不明白"),
                ("青い春を走れ", "奔跑在青春里"),
                ("考えたってわからないし", "怎么想都想不明白"),
                ("青空を見上げる", "仰望蔚蓝天空"),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "bleed.grammar-work"
            work.mkdir()
            write_json_atomic(work / "bilingual-lyrics.json", bilingual, replace=True)
            self.run_cli(str(scripts / "verify_translation.py"), str(work))
            (work / "blocks-plan.json").write_text(
                json.dumps(
                    {
                        "blocks": [
                            {"lines": ["l_001-l_002"], "meaning": "怎么想都想不明白，奔跑在青春里。"},
                            {"lines": ["l_003", "l_004"], "meaning": "怎么想都想不明白，仰望蔚蓝天空。"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_cli(str(scripts / "scaffold_draft.py"), str(work), "--learner-language", "zh-CN")
            draft_path = work / "semantic-draft.json"
            draft = read_json(draft_path)
            cands = discover_repetition_candidates(draft, bilingual, learner_language="zh-CN")["candidates"]
            self.assertEqual(len(cands), 1)
            self.assertEqual(cands[0]["normalizedText"], "考えたってわからないし")
            rep_id = cands[0]["repetitionId"]

            # 2. Enrichment supports blocks + meaningUnits + excludedRepetitions
            enrichment_path = work / "enrichment.json"
            enrichment_path.write_text(
                json.dumps(
                    {
                        "blocks": [
                            {"blockId": "b_01", "notes": "第一段补充说明。"},
                        ],
                        "excludedRepetitions": [
                            {"repetitionId": rep_id, "reason": "测试显式排除该候选组。"}
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_cli(
                str(scripts / "resolve_spans.py"),
                str(draft_path),
                "--merge-enrichment",
                str(enrichment_path),
                "--in-place",
            )
            self.run_cli(
                str(scripts / "discover_repetitions.py"),
                str(draft_path),
                "--workdir",
                str(work),
                "--learner-language",
                "zh-CN",
                "--in-place",
                "--replace",
            )
            updated = read_json(draft_path)
            self.assertEqual(updated["blocks"][0]["notes"], "第一段补充说明。")
            self.assertEqual(updated["repetitionGroups"], [])
            self.assertEqual(updated["extensions"]["excludedRepetitions"][0]["repetitionId"], rep_id)
            _, rep_issues = validate_repetition_completion(updated, bilingual, learner_language="zh-CN")
            self.assertEqual(rep_issues, [])

    def test_cli_stage_scripts_end_to_end(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bilingual_lrc = base / "cli-song.lrc"
            bilingual_lrc.write_bytes(JA_TRANSLATED_LRC.read_bytes())
            work = base / "cli-song.grammar-work"

            # 1. Extract bilingual-lyrics.json from bilingual LRC
            self.run_cli(
                str(scripts / "extract_bilingual.py"),
                str(bilingual_lrc),
                "--from-bilingual-lrc",
                "--workdir",
                str(work),
                "--source-language",
                "ja",
                "--learner-language",
                "zh-CN",
            )
            bilingual_path = work / "bilingual-lyrics.json"
            self.assertTrue(bilingual_path.is_file())

            # 2. Verify translation freeze
            self.run_cli(
                str(scripts / "verify_translation.py"),
                str(work),
            )

            # 3. Create blocks-plan.json (using canonical l_001 IDs) & run scaffold_draft.py
            (work / "blocks-plan.json").write_text(
                json.dumps(
                    {
                        "blocks": [
                            {"lines": ["l_001", "l_002", "l_003"], "meaning": "你给我的那个小小约定，直到现在我还清楚地记着。"},
                            {"lines": ["l_004"], "meaning": "那是你给我的约定。"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            scaffold_res = self.run_cli(
                str(scripts / "scaffold_draft.py"),
                str(work),
                "--learner-language",
                "zh-CN",
            )
            self.assertIn("DRAFT INDEX", scaffold_res.stdout)
            self.assertIn("l_001..l_003", scaffold_res.stdout)
            self.assertIn("cp)", scaffold_res.stdout)
            draft_path = work / "semantic-draft.json"
            draft = read_json(draft_path)
            self.assertEqual(draft["schemaVersion"], 3)
            self.assertEqual(draft["blocks"][0]["lineIds"], ["l_001", "l_002", "l_003"])

            # 4. Merge enrichment
            enrichment_path = work / "enrichment.json"
            enrichment_path.write_text(
                json.dumps(
                    {
                        "phrases": [
                            {
                                "phraseId": "p_cli_first",
                                "kind": "phrase",
                                "role": "theme",
                                "labels": [{"namespace": "syntax", "key": "phrase"}],
                                "explanation": "测试短语的语法说明。",
                                "gloss": "测试短语",
                                "confidence": 0.9,
                                "occurrences": [
                                    {
                                        "occurrenceId": "po_cli_first_1",
                                        "blockId": draft["blocks"][0]["blockId"],
                                        "sourceSegments": [
                                            {"lineId": "l_001", "text": draft["lines"][0]["text"]}
                                        ],
                                    }
                                ],
                            }
                        ],
                        "grammarNotes": [
                            {
                                "noteId": "gn_cli_1",
                                "scope": {
                                    "blockIds": [draft["blocks"][0]["blockId"]],
                                    "phraseId": "p_cli_first",
                                    "occurrenceIds": ["po_cli_first_1"],
                                },
                                "explanation": "测试语法笔记。",
                                "labels": [{"namespace": "syntax", "key": "note"}],
                                "confidence": 0.9,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_cli(
                str(scripts / "resolve_spans.py"),
                str(draft_path),
                "--bilingual",
                str(bilingual_path),
                "--merge-enrichment",
                str(enrichment_path),
                "--in-place",
            )

            # 5. Discover repetitions in-place
            self.run_cli(
                str(scripts / "discover_repetitions.py"),
                str(draft_path),
                "--bilingual",
                str(bilingual_path),
                "--workdir",
                str(work),
                "--learner-language",
                "zh-CN",
                "--in-place",
                "--replace",
            )

            # 6. Isolation + Prepare + Audit Summary + Validate Audit + Finalize
            self.run_cli(
                str(scripts / "record_isolation.py"),
                str(work),
                "--stage",
                "grammar-analysis",
                "--artifact",
                str(draft_path),
                "--method",
                "native-subagent",
                "--child-transcript-id",
                "cli-child-grammar",
                "--parent-transcript-id",
                "cli-parent",
                "--replace",
            )
            self.run_cli(
                str(scripts / "prepare.py"),
                str(work),
                "--learner-language",
                "zh-CN",
            )
            summary_res = self.run_cli(
                str(scripts / "audit_summary.py"),
                str(work),
                "--emit-template",
                str(work / "semantic-audit.json"),
                "--replace",
            )
            self.assertIn("SEMANTIC AUDIT SUMMARY", summary_res.stdout)
            self.assertIn("phrase [p_cli_first]:", summary_res.stdout)
            self.assertNotIn("validate_audit.py ...", summary_res.stdout)

            # Template must default to pending with empty reviewed arrays and fail validation if untouched
            pending_audit = read_json(work / "semantic-audit.json")
            self.assertEqual(pending_audit["status"], "pending")
            self.assertEqual(pending_audit["reviewedBlockIds"], [])
            pending_check = subprocess.run(
                [
                    sys.executable,
                    str(scripts / "validate_audit.py"),
                    str(work / "analysis-candidate.json"),
                    "--candidate-hash",
                    str(work / "analysis-candidate.sha256"),
                    str(work / "semantic-audit.json"),
                    "--learner-language",
                    "zh-CN",
                    "--check-format",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(pending_check.returncode, 0)

            # Simulate round-1 fail report -> re-emitting template must archive it under audit-history/
            cand_doc = read_json(work / "analysis-candidate.json")
            fail_audit = dict(pending_audit)
            fail_audit["status"] = "fail"
            fail_audit["reviewedBlockIds"] = [b["blockId"] for b in cand_doc["blocks"]]
            fail_audit["reviewedMeaningUnitIds"] = [u["meaningUnitId"] for u in cand_doc["meaningUnits"]]
            fail_audit["findings"] = [
                {"code": "other", "severity": "error", "message": "模拟首轮审计发现的问题。"}
            ]
            write_json_atomic(work / "semantic-audit.json", fail_audit, replace=True)
            # Stage A self-check allows valid fail report with --check-format
            self.run_cli(
                str(scripts / "validate_audit.py"),
                str(work / "analysis-candidate.json"),
                "--candidate-hash",
                str(work / "analysis-candidate.sha256"),
                str(work / "semantic-audit.json"),
                "--learner-language",
                "zh-CN",
                "--check-format",
            )
            # Re-emit template archives the prior fail report into audit-history/
            self.run_cli(
                str(scripts / "audit_summary.py"),
                str(work),
                "--emit-template",
                str(work / "semantic-audit.json"),
                "--replace",
            )
            archived_reports = list((work / "audit-history").glob("semantic-audit-*.json"))
            self.assertEqual(len(archived_reports), 1)

            # Now write passing audit report
            pass_audit = read_json(work / "semantic-audit.json")
            pass_audit["status"] = "pass"
            pass_audit["reviewedBlockIds"] = [b["blockId"] for b in cand_doc["blocks"]]
            pass_audit["reviewedMeaningUnitIds"] = [u["meaningUnitId"] for u in cand_doc["meaningUnits"]]
            pass_audit["findings"] = []
            write_json_atomic(work / "semantic-audit.json", pass_audit, replace=True)

            self.run_cli(
                str(scripts / "record_isolation.py"),
                str(work),
                "--stage",
                "semantic-audit",
                "--artifact",
                str(work / "semantic-audit.json"),
                "--method",
                "native-subagent",
                "--child-transcript-id",
                "cli-child-audit",
                "--parent-transcript-id",
                "cli-parent",
                "--replace",
            )
            self.run_cli(
                str(scripts / "validate_audit.py"),
                str(work / "analysis-candidate.json"),
                "--candidate-hash",
                str(work / "analysis-candidate.sha256"),
                str(work / "semantic-audit.json"),
                "--learner-language",
                "zh-CN",
                "--bilingual",
                str(bilingual_path),
                "--isolation",
                str(work / "isolation-semantic-audit.json"),
            )
            output_path = base / "cli-song.grammar.json"
            self.run_cli(
                str(scripts / "finalize.py"),
                str(work),
                "--output",
                str(output_path),
                "--learner-language",
                "zh-CN",
            )
            proof_archive = base / "archived-proofs"
            self.run_cli(
                str(scripts / "validate_all.py"),
                str(output_path),
                "--workdir",
                str(work),
                "--learner-language",
                "zh-CN",
                "--archive-proofs",
                str(proof_archive),
                "--cleanup-workdir",
            )
            self.assertFalse(work.exists())
            self.assertTrue((proof_archive / "cli-song" / "isolation-semantic-audit.json").is_file())
            self.assertTrue((proof_archive / "cli-song" / "semantic-audit.json").is_file())
            self.assertEqual(len(list((proof_archive / "cli-song" / "audit-history").glob("*.json"))), 1)
            self.assertTrue(output_path.is_file())
            final_doc = read_json(output_path)
            self.assertEqual(final_doc["schemaVersion"], 3)
            self.assertNotIn("timeMs", json.dumps(final_doc))
            self.assertNotIn("lrcFile", json.dumps(final_doc))
            self.assertNotIn("songId", json.dumps(final_doc))

    def test_scaffold_draft_fails_without_blocks_plan(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            bilingual_lrc = base / "no-plan.lrc"
            bilingual_lrc.write_bytes(JA_TRANSLATED_LRC.read_bytes())
            work = base / "no-plan.grammar-work"
            self.run_cli(
                str(scripts / "extract_bilingual.py"),
                str(bilingual_lrc),
                "--from-bilingual-lrc",
                "--workdir",
                str(work),
            )
            self.run_cli(str(scripts / "verify_translation.py"), str(work))
            res = subprocess.run(
                [sys.executable, str(scripts / "scaffold_draft.py"), str(work)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertNotEqual(res.returncode, 0)
            self.assertIn("missing_blocks_plan", res.stderr)

    def test_batch_cli_pipeline_end_to_end(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            ja_lrc = base / "song-ja.lrc"
            en_lrc = base / "song-en.lrc"
            ja_lrc.write_bytes(JA_TRANSLATED_LRC.read_bytes())
            en_lrc.write_bytes(EN_TRANSLATED_LRC.read_bytes())

            # Extract bilingual JSON in batch
            self.run_cli(
                str(scripts / "extract_bilingual.py"),
                str(ja_lrc),
                str(en_lrc),
                "--from-bilingual-lrc",
                "--learner-language",
                "zh-CN",
            )
            ja_work = base / "song-ja.grammar-work"
            en_work = base / "song-en.grammar-work"
            ja_bi = ja_work / "bilingual-lyrics.json"
            en_bi = en_work / "bilingual-lyrics.json"
            self.assertTrue(ja_bi.is_file())
            self.assertTrue(en_bi.is_file())

            # Verify translation in batch
            self.run_cli(
                str(scripts / "verify_translation.py"),
                str(ja_bi),
                str(en_bi),
                "--batch",
            )

            # Prepare drafts + isolation + prepare + audit + finalize for both
            for slug, lang, lrc_bi in (
                ("song-ja", "ja", ja_bi),
                ("song-en", "en", en_bi),
            ):
                work = base / f"{slug}.grammar-work"
                bilingual = read_json(lrc_bi)
                (work / "blocks-plan.json").write_text(
                    json.dumps(
                        {
                            "blocks": [
                                {
                                    "lines": list(range(1, len(bilingual["lines"]) + 1)),
                                    "meaning": "完整段落的自然意译说明。",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                self.run_cli(
                    str(scripts / "scaffold_draft.py"),
                    str(work),
                    "--learner-language",
                    "zh-CN",
                )
                draft_path = work / "semantic-draft.json"
                self.run_cli(
                    str(scripts / "discover_repetitions.py"),
                    str(draft_path),
                    "--bilingual",
                    str(lrc_bi),
                    "--workdir",
                    str(work),
                    "--learner-language",
                    "zh-CN",
                    "--in-place",
                    "--replace",
                )
                self.run_cli(
                    str(scripts / "record_isolation.py"),
                    str(work),
                    "--stage",
                    "grammar-analysis",
                    "--artifact",
                    str(draft_path),
                    "--method",
                    "native-subagent",
                    "--child-transcript-id",
                    f"child-g-{slug}",
                    "--parent-transcript-id",
                    "batch-parent",
                    "--replace",
                )
                self.run_cli(
                    str(scripts / "prepare.py"),
                    str(work),
                    "--learner-language",
                    "zh-CN",
                )
                self.run_cli(
                    str(scripts / "audit_summary.py"),
                    str(work),
                    "--emit-template",
                    str(work / "semantic-audit.json"),
                    "--replace",
                )
                cand_doc = read_json(work / "analysis-candidate.json")
                audit_doc = read_json(work / "semantic-audit.json")
                audit_doc["status"] = "pass"
                audit_doc["reviewedBlockIds"] = [b["blockId"] for b in cand_doc["blocks"]]
                audit_doc["reviewedMeaningUnitIds"] = [u["meaningUnitId"] for u in cand_doc["meaningUnits"]]
                write_json_atomic(work / "semantic-audit.json", audit_doc, replace=True)
                self.run_cli(
                    str(scripts / "record_isolation.py"),
                    str(work),
                    "--stage",
                    "semantic-audit",
                    "--artifact",
                    str(work / "semantic-audit.json"),
                    "--method",
                    "native-subagent",
                    "--child-transcript-id",
                    f"child-a-{slug}",
                    "--parent-transcript-id",
                    "batch-parent",
                    "--replace",
                )

            self.run_cli(
                str(scripts / "status.py"),
                str(ja_work),
                str(en_work),
            )
            self.run_cli(
                str(scripts / "finalize.py"),
                str(ja_work),
                str(en_work),
                "--learner-language",
                "zh-CN",
            )
            self.run_cli(
                str(scripts / "validate_all.py"),
                str(base / "song-ja.json"),
                str(base / "song-en.json"),
                "--batch",
                "--learner-language",
                "zh-CN",
                "--cleanup-workdir",
            )
            self.assertFalse(ja_work.exists())
            self.assertFalse(en_work.exists())
            self.assertTrue((base / "song-ja.json").is_file())
            self.assertTrue((base / "song-en.json").is_file())

    def test_discover_repetitions_check_draft_catches_partial_overlap(self) -> None:
        scripts = SKILL_ROOT / "scripts"
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / "partial.grammar-work"
            work.mkdir(parents=True, exist_ok=True)
            bilingual = make_bilingual_from_lrc_lines(
                [
                    ("一度だけの恋なら 君の中で遊ぼう", "倘若爱恋仅有一次 就在你心中嬉戏吧"),
                    ("このまま", "就这样"),
                    ("一度だけの恋なら 君の中で遊ぼう", "倘若爱恋仅有一次 就在你心中嬉戏吧"),
                ],
                source_languages=["ja"],
                learner_language="zh-CN",
            )
            write_json_atomic(work / "bilingual-lyrics.json", bilingual, replace=True)
            self.run_cli(str(scripts / "verify_translation.py"), str(work))
            (work / "blocks-plan.json").write_text(
                json.dumps(
                    {
                        "blocks": [
                            {"lines": ["l_001", "l_002"], "meaning": "倘若爱恋仅有一次就在你心中嬉戏吧就这样。"},
                            {"lines": ["l_003"], "meaning": "倘若爱恋仅有一次就在你心中嬉戏吧。"},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_cli(str(scripts / "scaffold_draft.py"), str(work), "--learner-language", "zh-CN")
            draft_path = work / "semantic-draft.json"
            check_res = subprocess.run(
                [
                    sys.executable,
                    str(scripts / "discover_repetitions.py"),
                    str(draft_path),
                    "--workdir",
                    str(work),
                    "--learner-language",
                    "zh-CN",
                    "--in-place",
                    "--replace",
                    "--check-draft",
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(check_res.returncode, 2)
            self.assertIn("shared-occurrence-incomplete", check_res.stderr)
            self.assertIn("HINT:", check_res.stderr)

            enrichment_path = work / "enrichment.json"
            enrichment_path.write_text(
                json.dumps(
                    {
                        "blocks": [
                            {
                                "blockId": "b_01",
                                "meaning": {
                                    "parts": [
                                        {"meaningUnitOccurrenceId": "muo_b_01_rep"},
                                        {"meaningUnitOccurrenceId": "muo_b_01_tail"},
                                    ]
                                },
                            }
                        ],
                        "meaningUnits": [
                            {
                                "meaningUnitId": "mu_b_02",
                                "text": "倘若爱恋仅有一次，就在你心中尽情嬉戏吧。",
                                "labels": [],
                                "confidence": 0.9,
                                "occurrences": [
                                    {
                                        "occurrenceId": "muo_b_01_rep",
                                        "blockId": "b_01",
                                        "sourceSegments": [{"lineId": "l_001", "text": "一度だけの恋なら 君の中で遊ぼう"}],
                                    },
                                    {
                                        "occurrenceId": "muo_b_02",
                                        "blockId": "b_02",
                                        "sourceSegments": [{"lineId": "l_003", "text": "一度だけの恋なら 君の中で遊ぼう"}],
                                    },
                                ],
                            },
                            {
                                "meaningUnitId": "mu_b_01_tail",
                                "text": "就这样。",
                                "labels": [],
                                "confidence": 0.9,
                                "occurrences": [
                                    {
                                        "occurrenceId": "muo_b_01_tail",
                                        "blockId": "b_01",
                                        "sourceSegments": [{"lineId": "l_002", "text": "このまま"}],
                                    }
                                ],
                            },
                        ],
                        "phrases": [],
                        "relations": [],
                        "grammarNotes": [],
                        "uncertainties": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            self.run_cli(
                str(scripts / "resolve_spans.py"),
                str(draft_path),
                "--merge-enrichment",
                str(enrichment_path),
                "--in-place",
            )
            self.run_cli(
                str(scripts / "discover_repetitions.py"),
                str(draft_path),
                "--workdir",
                str(work),
                "--learner-language",
                "zh-CN",
                "--in-place",
                "--replace",
                "--check-draft",
            )


if __name__ == "__main__":
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    sys.dont_write_bytecode = True
    configure_utf8_stdio()
    unittest.main(verbosity=2)
