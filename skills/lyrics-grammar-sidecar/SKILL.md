---
name: lyrics-grammar-sidecar
description: Generates, enriches, audits, and validates pure-content Schema v3 lyrics grammar sidecars (`<song>.json`). Use whenever the user asks to produce or refresh grammar, phrase, or stanza meaning analysis for lyrics from `<workdir>/bilingual-lyrics.json` + `<workdir>/blocks-plan.json` (from `sakurauta-lyrics-workflow`) or an external bilingual `.lrc` file (even if they only mention "语法解析", "段落分析", "sidecar", or bilingual lyrics).
metadata:
  version: "4.1.0"
---

# Lyrics Grammar Sidecar (Schema v3)

Produces a validated, timestamp-free Schema v3 grammar analysis sidecar `<song>.json` (`schema: "sakurauta.lyrics-grammar-analysis"`, `schemaVersion: 3`) containing only normalized lyric content, semantic blocks, canonical meaning units, phrases, relations, grammar notes, and uncertainties — with zero timestamps, zero file/song identifiers (`lrcFile`, `songId`), and zero metadata blocks (`b_meta`).

Resolve `<grammar-skill>` to the directory containing this `SKILL.md` and `<workdir>` to `<song>.grammar-work` before running commands. Always run Python with `python -X utf8` on Windows and quote every path.

> For exact JSON schemas, `DRAFT INDEX` format, and `enrichment.json` keys, read [draft-contract.md](references/draft-contract.md). For audit checklists, pending-template rules, and two-stage audit validation, read [semantic-audit-contract.md](references/semantic-audit-contract.md).

## Inputs & Handoff Paths

Every analysis starts from a single timestamp-free source of truth: `<workdir>/bilingual-lyrics.json` paired with `<workdir>/blocks-plan.json`.

- **Path A — From `sakurauta-lyrics-workflow` (standard)**: Phase 2 has already exported `<workdir>/bilingual-lyrics.json` and Stage 3 Arbiter has already written `<workdir>/blocks-plan.json` (using `l_001`..`l_NNN` IDs). Skip `extract_bilingual.py` and start at Step 2 (`verify_translation.py`).
- **Path B — From an external bilingual `.lrc` file**: Run `extract_bilingual.py <bilingual.lrc> --from-bilingual-lrc` to produce `<workdir>/bilingual-lyrics.json`. If `<workdir>/blocks-plan.json` does not exist yet, Grammar Child creates it from `bilingual-lyrics.frozen.json` using `l_001`..`l_NNN` IDs before running `scaffold_draft.py`.

### Deterministic Lyric Line Filtering Rules

When `extract_bilingual.py` reads an `.lrc` file, timestamps are used in-memory solely to filter non-lyric rows and then discarded:

- Excludes untimed metadata tags (`[ti:]`, `[ar:]`, `[al:]`, `[by:]`, `[offset:]`, `[yt:]`, `[youtube:]`), blank lines, and credit lines (`词：`, `曲：`, `编曲：`, `作词：`, `Lyrics:`, `Music:`, etc.).
- Deduplicates same-timestamp translation rows so only primary source lines receive `l_001`..`l_NNN` IDs (with their paired translation stored in `translation`).
- Excludes `<= 2.5s` `Title - Artist` header lines matching the filename stem when real lyric lines follow. Never synthesize a `b_meta` block.

## Pipeline Overview

Two separate fresh subagents are required so the grammar author never audits its own output (`isolation-grammar-analysis.json` and `isolation-semantic-audit.json` must carry distinct `childTranscriptId` values). Only the orchestrator runs freezing, isolation recording, candidate preparation, finalization, and cleanup scripts.

```text
bilingual-lyrics.json + blocks-plan.json
  -> verify_translation.py    (freeze bilingual-lyrics.frozen.json + manifest)
  -> Grammar Child            (scaffold_draft -> enrichment.json -> resolve_spans -> discover_repetitions)
  -> record_isolation.py      (--stage grammar-analysis)
  -> prepare.py               (validate v3 schema/repetitions -> freeze analysis-candidate.json)
  -> Audit Child              (audit_summary --emit-template [pending] -> edit report -> validate_audit --check-format)
  -> [If fail: batch ALL findings into 1 Grammar Child fix pass -> re-prepare -> 2nd Audit Child; max 2 rounds]
  -> record_isolation.py      (--stage semantic-audit)
  -> validate_audit.py        (Stage B full gate with --bilingual and --isolation)
  -> finalize.py              (verify full proof chain -> atomic <song>.json)
  -> validate_all.py          (--cleanup-workdir [--archive-proofs <dir>])
```

## Orchestrator Commands (Single or Batch)

Always keep `--learner-language <target>` identical across every script from `extract_bilingual.py` through `validate_all.py` (for example, `zh-CN` or `zh` consistently; do not mix `zh` and `zh-CN` mid-pipeline).

1. **Extract bilingual JSON (Path B only; skip in Path A):**

   ```powershell
   python -X utf8 "<grammar-skill>/scripts/extract_bilingual.py" "<song.lrc>" --from-bilingual-lrc --source-language <lang> --learner-language <target>
   ```

2. **Freeze translation baseline (Orchestrator):**

   ```powershell
   python -X utf8 "<grammar-skill>/scripts/verify_translation.py" "<workdir>"
   ```

3. **Dispatch Grammar Child (fresh Subagent A; pass ONLY `<workdir>/bilingual-lyrics.frozen.json`, `<workdir>/blocks-plan.json` if present, and `<grammar-skill>/references/draft-contract.md`):**
   - Path B only: if `<workdir>/blocks-plan.json` is missing, create it from `bilingual-lyrics.frozen.json` using `l_001`..`l_NNN` IDs (never add `b_meta`).
   - Run `python -X utf8 "<grammar-skill>/scripts/scaffold_draft.py" "<workdir>" --learner-language "<target>"` to create `semantic-draft.json` and print the compact `DRAFT INDEX` (block ranges + per-line Unicode code-point counts).
   - Write `<workdir>/enrichment.json` using the supported top-level keys: `phrases`, `grammarNotes`, `relations`, `uncertainties`, and optionally `meaningUnits`, `blocks` (patch by `blockId`: `meaning`, `labels`, `register`, `notes`, `confidence`), and `excludedRepetitions` (`[{"repetitionId": "...", "reason": "..."}]`). If a block only partially overlaps a repeated chorus/hook, split its `meaningUnits` and `blocks[].meaning.parts` into the shared span and the non-overlapping remainder per `draft-contract.md`.
   - Run `python -X utf8 "<grammar-skill>/scripts/resolve_spans.py" "<workdir>/semantic-draft.json" --merge-enrichment "<workdir>/enrichment.json" --in-place`.
   - Run `python -X utf8 "<grammar-skill>/scripts/discover_repetitions.py" "<workdir>/semantic-draft.json" --workdir "<workdir>" --learner-language "<target>" --in-place --replace --check-draft` (optionally pass `--exclude "<rep_id>=<reason>"` for spurious cross-line substring candidates). Fix any `--check-draft` errors (such as `shared-occurrence-incomplete`) before returning.
   - Return `draftPath` (`<workdir>/semantic-draft.json`). The orchestrator captures Subagent A's `conversationId` from `invoke_subagent` as `<grammar_child_id>`.

4. **Record grammar isolation & freeze candidate (Orchestrator):**

   ```powershell
   python -X utf8 "<grammar-skill>/scripts/record_isolation.py" "<workdir>" --stage grammar-analysis --artifact "<workdir>/semantic-draft.json" --method native-subagent --child-transcript-id "<grammar_child_id>" --parent-transcript-id "<parent_id>" --replace && python -X utf8 "<grammar-skill>/scripts/prepare.py" "<workdir>" --learner-language "<target>"
   ```

5. **Dispatch Audit Child (fresh Subagent B with a DIFFERENT `conversationId`; pass ONLY `<workdir>/bilingual-lyrics.frozen.json`, `<workdir>/analysis-candidate.json`, `<workdir>/analysis-candidate.sha256`, and `<grammar-skill>/references/semantic-audit-contract.md`):**
   - Run `python -X utf8 "<grammar-skill>/scripts/audit_summary.py" "<workdir>" --emit-template "<workdir>/semantic-audit.json" --replace`. This prints the aligned review table, flags suspiciously short multi-line block meanings, archives any prior completed audit into `<workdir>/audit-history/`, and writes a **`status: "pending"`** template with empty `reviewedBlockIds` and `reviewedMeaningUnitIds`.
   - Independently inspect every block, meaningUnit, phrase, grammarNote, and any `excludedRepetitions` entry against `bilingual-lyrics.frozen.json`. Populate `reviewedBlockIds`, `reviewedMeaningUnitIds`, `findings`, and set `status` to `"pass"` or `"fail"`.
   - Run **Stage A self-check** (NO `--bilingual` and NO `--isolation`, because the audit isolation proof does not exist yet):

     ```powershell
     python -X utf8 "<grammar-skill>/scripts/validate_audit.py" "<workdir>/analysis-candidate.json" --candidate-hash "<workdir>/analysis-candidate.sha256" "<workdir>/semantic-audit.json" --learner-language "<target>" --check-format
     ```

   - Return the audit `status` and findings summary. The orchestrator captures Subagent B's `conversationId` from `invoke_subagent` as `<audit_child_id>`.
   - **Batch-Fix Loop (max 2 audit rounds)**: If Audit Child reports `status: "fail"`, pass ALL findings together to a single Grammar Child revision pass (do not iterate one typo at a time), re-run `resolve_spans.py` -> `discover_repetitions.py --check-draft` -> `record_isolation.py --stage grammar-analysis --replace && prepare.py`, and run a second Audit Child pass. Escalate to the user if round 2 still fails.

6. **Record audit isolation, run Stage B gate, finalize, and clean up (Orchestrator):**

   ```powershell
   python -X utf8 "<grammar-skill>/scripts/record_isolation.py" "<workdir>" --stage semantic-audit --artifact "<workdir>/semantic-audit.json" --method native-subagent --child-transcript-id "<audit_child_id>" --parent-transcript-id "<parent_id>" --replace && python -X utf8 "<grammar-skill>/scripts/validate_audit.py" "<workdir>/analysis-candidate.json" --candidate-hash "<workdir>/analysis-candidate.sha256" "<workdir>/semantic-audit.json" --learner-language "<target>" --bilingual "<workdir>/bilingual-lyrics.frozen.json" --isolation "<workdir>/isolation-semantic-audit.json" && python -X utf8 "<grammar-skill>/scripts/finalize.py" "<workdir>" --learner-language "<target>" --replace && python -X utf8 "<grammar-skill>/scripts/validate_all.py" "<song.json>" --workdir "<workdir>" --learner-language "<target>" --cleanup-workdir
   ```

   - To preserve isolation proofs and `audit-history/` outside `<workdir>` before cleanup, pass `--archive-proofs "<proof-archive-dir>"` to `validate_all.py`.
   - Inspect multi-song progress anytime with `python -X utf8 "<grammar-skill>/scripts/status.py" "<target-dir>"` or run standalone validation with `python -X utf8 "<grammar-skill>/scripts/validate.py" "<song.json>" --bilingual "<bilingual-lyrics.json>" --learner-language "<target>"`.

## Non-Negotiable Invariants

- **Timestamp & File Agnostic**: Never write `timeMs`, `startTimeMs`, `endTimeMs`, `lrcFile`, `songId`, or `lrcProjectionHash` into Schema v3 artifacts.
- **Canonical Sequential Line IDs**: `lineId` is strictly sequential 1-based (`l_001`, `l_002`, ...) matching NFC source lines after deterministic metadata, credit, blank-line, and `<= 2.5s` header filtering; never synthesize `b_meta`.
- **No Unaudited Semantic Edits**: Any semantic edit to `semantic-draft.json` after `prepare.py` requires re-running `discover_repetitions.py` -> `record_isolation.py --stage grammar-analysis --replace` -> `prepare.py` -> a fresh Audit Child pass before `finalize.py`.
- **Clean Learner-Language Prose**: Keep every learner-facing field (`meaningUnits`, `phrases`, `grammarNotes`, `uncertainties`, `excludedRepetitions[].reason`) plain text in `--learner-language` with zero HTML/XML tags, absolute file paths, or translation keys.
