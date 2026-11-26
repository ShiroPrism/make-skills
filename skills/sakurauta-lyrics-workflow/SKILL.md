---
name: sakurauta-lyrics-workflow
description: End-to-end bilingual LRC translation and pure-content Schema v3 lyrics grammar JSON pipeline. Use whenever the user asks to translate an `.lrc` file and generate its companion `.json` grammar analysis sidecar, or hand off translated lyrics from `lyrics-translator` to `lyrics-grammar-sidecar`.
metadata:
  version: "4.1.0"
---

# Lyrics Translation & Grammar Sidecar Workflow

Coordinates **`lyrics-translator`** and **`lyrics-grammar-sidecar`** for local `.lrc` files to produce two outputs: an updated bilingual `.lrc` and a timestamp-free Schema v3 grammar analysis `.json`.

Resolve these absolute paths once before running commands:

- `<translator-skill>`: directory containing `lyrics-translator/SKILL.md`
- `<grammar-skill>`: directory containing `lyrics-grammar-sidecar/SKILL.md`
- `<workdir>`: `<song>.grammar-work` beside `<song>.lrc`

Always invoke Python scripts with `python -X utf8` on Windows and quote every file path.

## Pipeline Phases

### Phase 1: Single-Draft 3-Stage Translation (`lyrics-translator` Stages 1–3)

1. **Orchestrator — Strip timestamps & emit canonical lyric index**:

   ```powershell
   python -X utf8 "<translator-skill>/scripts/lrc_strip.py" "<song.lrc>" && python -X utf8 "<grammar-skill>/scripts/extract_bilingual.py" "<song.lrc>" --emit-index
   ```

   `lrc_strip.py` creates `<song.lrc>.tmp.txt` for translation. `extract_bilingual.py --emit-index` writes `<workdir>/lyric-index.txt` listing every kept lyric line as `l_001 | <text>` after removing untimed `[ti:]/[ar:]` metadata tags, credit lines, blank lines, and `<= 2.5s` `Title - Artist` header lines. Use `l_001`..`l_NNN` IDs for all stanza planning so credit offsets can never cause line-number drift.

2. **Stage 1 — Initial Translator (1 fresh subagent reading `<translator-skill>/roles/translator.md`)**:
   - Translates `<song.lrc>.tmp.txt` into the target learner language.
   - Outputs ONLY the Song Persona Handover Memo with **proposed stanza groupings** referencing `l_001`..`l_NNN` IDs from `<workdir>/lyric-index.txt`. Does NOT write `blocks-plan.json`.

3. **Stage 2 — Adversarial Reviewer (1 fresh isolated subagent reading `<translator-skill>/roles/reviewer.md`)**:
   - Audits `<song.lrc>.tmp.txt`, the original `.lrc`, `<workdir>/lyric-index.txt`, and the Translator's Handover Memo (including proposed stanza boundaries).
   - Outputs structured Issue Directives (`Critical Defects` and `Stylistic Polish`).

4. **Stage 3 — Arbiter (1 subagent reading `<translator-skill>/roles/arbiter.md` and Section 2 of `<grammar-skill>/references/draft-contract.md`)**:
   - Arbitrates directives, polishes cadence, and writes the finalized `<song.lrc>.tmp.txt` in a single pass.
   - Acts as the **sole author** of `<workdir>/blocks-plan.json`, writing natural stanza blocks using `l_001`..`l_NNN` IDs from `<workdir>/lyric-index.txt` (e.g. `{"lines": ["l_001", "l_002", "l_003"], "meaning": "..."}`) with terminology aligned to `.tmp.txt` and full monotonic line coverage per `draft-contract.md`.
   - **STOP before `lrc_merge.py`**: Under this workflow, the Arbiter MUST NOT run `lrc_merge.py` (which deletes `.tmp.txt`). Return control to the orchestrator with `.tmp.txt` intact.

### Phase 2: Pure-Content Bilingual Handoff & LRC Merge (Orchestrator Only)

Choose one canonical `<learner_lang>` tag (for example `zh-CN` or `zh`) and pass it identically to every Phase 2 and Phase 3 command (`lyrics-translator` normalizes `zh-CN` -> `zh.md`).

```powershell
python -X utf8 "<grammar-skill>/scripts/extract_bilingual.py" "<song.lrc>" --source-language <lang> --learner-language <learner_lang> && python -X utf8 "<translator-skill>/scripts/lrc_merge.py" "<song.lrc>" "<song.lrc>.tmp.txt" && python -X utf8 "<grammar-skill>/scripts/verify_translation.py" "<workdir>"
```

- `extract_bilingual.py` discards all timestamps, assigns canonical `l_001`..`l_NNN` IDs and `contentHash`, and pairs every kept lyric line with its finalized `.tmp.txt` translation (or `null` for vocal fillers / untranslated lines), preserving context-specific translations across repeated lines into `<workdir>/bilingual-lyrics.json`.
- `lrc_merge.py` aligns repeated source lines in occurrence order so the merged `.lrc` stays consistent with `bilingual-lyrics.json`, verifies `[OK]`, and deletes `.tmp.txt`.
- `verify_translation.py` freezes `<workdir>/bilingual-lyrics.frozen.json` and writes the translation manifest for Phase 3.

### Phase 3: Schema v3 Grammar Sidecar (`lyrics-grammar-sidecar`)

Invoke **`lyrics-grammar-sidecar`** via **Path A** (skipping `extract_bilingual.py` and `verify_translation.py`, since `<workdir>/bilingual-lyrics.frozen.json` and `<workdir>/blocks-plan.json` already exist):

1. **Grammar Child (Subagent A)**: `scaffold_draft.py` -> write compact `enrichment.json` (splitting `meaningUnits` and `blocks[].meaning.parts` whenever a block only partially overlaps a repeated chorus/hook) -> `resolve_spans.py --merge-enrichment ... --in-place` -> `discover_repetitions.py ... --in-place --replace --check-draft` -> return `draftPath` (orchestrator captures Subagent A's `conversationId` as `--child-transcript-id`).
2. **Record grammar isolation & prepare candidate (Orchestrator)**: `record_isolation.py --stage grammar-analysis ... && prepare.py ...`
3. **Audit Child (Subagent B, distinct `conversationId`)**: `audit_summary.py --emit-template` (emits `status: "pending"`) -> inspect candidate vs `bilingual-lyrics.frozen.json` -> fill `reviewedBlockIds`, `reviewedMeaningUnitIds`, `findings`, and set `status` to `"pass"` or `"fail"` -> run Stage A self-check (`validate_audit.py ... --check-format`, without `--bilingual`/`--isolation`) -> return `status` and findings summary (orchestrator captures Subagent B's `conversationId` as `--child-transcript-id`). If `"fail"`, batch all findings into one Grammar Child fix pass and re-audit (maximum 2 audit rounds total).
4. **Finalize & validate (Orchestrator)**: `record_isolation.py --stage semantic-audit ... && validate_audit.py ... --bilingual ... --isolation ... && finalize.py ... && validate_all.py ... --cleanup-workdir` (optionally add `--archive-proofs "<archive-dir>"` to keep proofs and audit history).

## Concurrency for Multi-File Batches

Keep each song isolated in its own child contexts (never bundle multiple songs into one prompt). Size active concurrency to the runtime's available subagent slots (for example, 1–2 concurrent songs in a 4-slot environment; prioritize completing one song end-to-end when slots are tight).

## Output Artifacts

- **Bilingual `.lrc`**: `<song.lrc>` updated in-place with interleaved source/translation timestamps.
- **Grammar sidecar `<song>.json`**: Timestamp-free, file-agnostic Schema v3 JSON sidecar anchored purely by normalized lyric text.
- Temporary `.tmp.txt` and `.grammar-work/` directories are removed automatically once final validation passes.
