---
name: sakurauta-lyrics-workflow
description: "Create bilingual LRC translations and SakuraUta Schema v2 grammar-analysis sidecars. Coordinates fresh child roles for translation (Adversarial 3-Stage Pipeline: Translator → Reviewer in clean context → Arbiter/Merge), grammar analysis, and independent semantic audit; deterministic scripts freeze and finalize the contract. Automatically activates batch workflow when a directory or multiple LRC files are specified or discovered."
metadata:
  version: "3.0.0"
---

# SakuraUta Lyrics Workflow v2

The parent coordinates independent child roles. It does not translate, invent grammar analysis, or self-audit semantics inline.

1. Translation Stage (when translation is required): coordinates the `lyrics-translator` Adversarial 3-Stage Pipeline (Stage 1 Translator child → Stage 2 Adversarial Reviewer child in fresh context → Stage 3 Arbiter/Finalizer) to eliminate confirmation bias and idiom traps before educational analysis begins.
2. Grammar child: authors only the v2 semantic draft. A deterministic tool writes its repetition-candidate list, and the parent freezes the candidate.
3. Semantic-audit child: a different fresh transcript that reviews the frozen candidate and writes only the audit report.

Only the deterministic finalizer writes `<song>.json`.

Translation is optional when the LRC is already an accepted bilingual file. It is a prerequisite only when the user needs a new translation; the grammar Sidecar itself is not runtime-dependent on `lyrics-translator`.

## Inputs

- local source `.lrc`;
- target learner language, for example `zh-CN`;
- SakuraUta `songId` (default: LRC basename without `.lrc`).

Work directory: `<song>.grammar-work` beside the source.

Quote all file paths in PowerShell commands (especially when titles contain special characters like semicolons `;`, ampersands `&`, dollars `$`, or apostrophes `'`).

Reject video, subtitle, remote, non-LRC, network-share, and symlinked inputs.

## Isolation Gate

A child is a fresh non-forked sub-agent or a fresh independent CLI transcript. Loading a Skill into the parent is not isolation.

To avoid inheriting ~18k+ tokens of parent MCP schemas and unrelated skills on every fresh child (`TypeName: "self"`), prefer defining lightweight dedicated subagent types once via `define_subagent` (`EnableWriteTools: true`, `EnableMCPTools: false`, `EnableSubagentTools: false` for Translator, Grammar Analyst, and Semantic Auditor) and using the built-in read-only `research` subagent for the Adversarial Reviewer.

The grammar and semantic-audit children must have different `childTranscriptId` values. When the harness exposes parent IDs, both children must also differ from the parent. If separate contexts are unavailable, stop with:

```text
ERROR [isolation-unavailable]
```

Never fall back to inline translation, grammar analysis, or self-audit.

## Phase 1: Translate and Freeze

Execute the Adversarial 3-Stage Translation Pipeline via `lyrics-translator` to produce both the bilingual translation and the mandatory `<workdir>\blocks-plan.json`:

1. **Step 1: Project Source & Strip Timestamps**:

   ```powershell
   python <grammar-skill>\scripts\project_source.py "<song.lrc>" `
     --song-id "<songId>"
   python <translator-skill>\scripts\lrc_strip.py "<song.lrc>"
   ```

   `project_source.py` canonicalizes the source rows (ignoring blank timestamp lines and interleaved translations) and creates `<workdir>\source-projection.json` upfront so Stage 1 and Stage 2 index `blocks-plan.json` directly against `1..lineCount`. `lrc_strip.py` generates `<song.lrc>.tmp.txt` in the same directory. No-Read Principle applies: the parent does not need to read `<song.lrc>.tmp.txt` before dispatching Stage 1; exit code 0 is authoritative.

2. **Step 2: Dispatch Translator Child (Stage 1)**:

   ```text
   Read and follow <skills>\lyrics-translator\roles\translator.md and its referenced linguistic profiles in <skills>\lyrics-translator\reference\ (map regional tags like zh-CN/zh-TW to reference/target/zh.md).
   Translate the working file <song.lrc>.tmp.txt into <target learner language> using Dual-Track Mode:
   - Track 1: Write strictly time-aligned line-by-line translation to <song.lrc>.tmp.txt without inverting cross-line word order or leaving a dangling line-ending 的 on modifier splits; match multi-syllable hooks with cadence-appropriate idioms rather than clipping them.
   - Track 2: Record natural semantic stanza groups and fluent literary meanings into <workdir>\blocks-plan.json, indexing 1..lineCount against <workdir>\source-projection.json (if .tmp.txt has no blank lines or metadata tags, its lines already match 1..lineCount 1:1 without needing to read source-projection.json) and keeping locked key terms identical to Track 1.
   Output ONLY the Song Persona, Theme, and blocks plan handover memo upon completion.
   Do NOT dump or print the full translated lyrics in your response (the disk file is authoritative).
   Do not produce grammar JSON.
   ```

3. **Step 3: Dispatch Adversarial Reviewer Child (Stage 2 — Clean Isolated Context)**: Dispatch a **separate, fresh subagent** with zero memory of the translator's thought process:

   ```text
   Read and follow <skills>\lyrics-translator\roles\reviewer.md.
   Audit the draft translation in <song.lrc>.tmp.txt and stanza segmentation in <workdir>\blocks-plan.json against original source lyrics, <workdir>\source-projection.json, and translator's Handover Memo.
   Execute the Adversarial Falsification Protocol:
   - Identify dictionary first-sense traps (e.g., polysemous idioms or rhetorical phrases translated literally).
   - Identify contextual contradictions (emotional or causal breaks with surrounding lines).
   - Identify register collapse, narrative persona drift, dangling line-ending 的 on SOV modifier splits, and weight collapse on multi-syllable hooks.
   - Audit stanza boundaries & cross-track alignment: ensure mid-sentence enjambments are never severed across blocks, indices cover 1..lineCount with no skipped/out-of-range lines, and Track 1 / Track 2 key terms unify onto the stronger phrasing.
   - Enforce red lines (no plot injection, length within cap, metadata immunity).
   Output your structured critique report according to roles\reviewer.md.
   ```

4. **Step 4: Arbiter & Deterministic Merge (Stage 3)**:
   - Mandatorily adopt all critical defect fixes identified by the Reviewer child; arbitrate stylistic suggestions against the Song Persona.
   - Apply polished lines to `<song.lrc>.tmp.txt` in a single write pass or script execution (avoid multi-turn single-line edit calls), eliminating any dangling line-ending `的` and unifying core hooks across both tracks.
   - Commit the audited stanza boundaries, exact `1..lineCount` indices, and term-aligned meanings to `<workdir>\blocks-plan.json`.
   - Run the deterministic merge script:
     ```powershell
     python <translator-skill>\scripts\lrc_merge.py "<song.lrc>" "<song.lrc>.tmp.txt"
     ```
   - Verify the console outputs `[OK]`. (No-Read Verification Principle: do NOT manually re-read the merged `.lrc` file; exit code 0 is authoritative).

5. **Step 5: Freeze Accepted Translation**: Freeze the finalized bilingual LRC (or pause for user confirmation first when interactive translation review is requested):
   ```powershell
   python <grammar-skill>\scripts\verify_translation.py `
     "<workdir>\source-projection.json" `
     "<song.lrc>" `
     --workdir "<workdir>"
   ```
   This verifies the bilingual handoff in `<song.lrc>` against the source projection, freezes a snapshot to `<workdir>\translated.lrc`, and writes `translation-manifest.json`. (If the accepted translation resides in an alternate file, pass that path as `<accepted-lrc>` instead). The parent owns acceptance. Do not proceed if freezing fails. Do not edit `translated.lrc` after this point. The freeze is an audit snapshot; the production JSON remains self-contained and does not require recipients to ship `.grammar-work`.

## Phase 2: Fresh Grammar Analysis

6. Dispatch a grammar child different from the parent:

```text
Read and follow <grammar-skill>\references\draft-contract.md (do not waste context reading SKILL.md or JSON Schema files).
Step 1: Run scaffold_draft.py to generate the initial compliant draft and print the compact DRAFT INDEX and REPETITION GROUPS to stdout:
  python -X utf8 <grammar-skill>\scripts\scaffold_draft.py "<workdir>" --learner-language "<target>" --auto-repetitions
Step 2: Using only the printed DRAFT INDEX (do NOT read semantic-draft.json), write <workdir>\enrichment.json containing educational phrases and grammarNotes in <target>.
Step 3: Merge enrichment.json, automatically compute code-point spans, and verify 100% of validation rules in one command:
  python -X utf8 <grammar-skill>\scripts\resolve_spans.py "<workdir>\semantic-draft.json" --projection "<workdir>\source-projection.json" --merge-enrichment "<workdir>\enrichment.json" --in-place && python -X utf8 <grammar-skill>\scripts\validate.py "<workdir>\semantic-draft.json" --projection "<workdir>\source-projection.json" --learner-language "<target>"
STRICT RULES:
- Do not inspect or read internal scripts (v2lib.py, sidecarlib.py, etc.) or write scratch Python scripts.
- Do not read or dump the full semantic-draft.json, LRC, or JSON Schema files into context, and never perform sequential line-by-line edit_file calls on semantic-draft.json.
- Write only <workdir>\semantic-draft.json (via scaffold_draft.py / resolve_spans.py) and <workdir>\enrichment.json. Do not write isolation proofs or <song>.json, and do not alter the frozen translation.
```

7. After the grammar child returns, record the actual grammar-child identity:

```powershell
python <grammar-skill>\scripts\record_isolation.py "<workdir>" `
  --stage grammar-analysis `
  --child-transcript-id "<actual-grammar-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

8. Prepare and freeze the repetition-candidate list deterministically:

```powershell
python <grammar-skill>\scripts\prepare.py "<song.lrc>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<target>"
```

`prepare.py` validates Schema v2 conformance, repetition discovery/completion, and writes `<workdir>\analysis-candidate.json` along with its cryptographic hash `<workdir>\analysis-candidate.sha256`. Do not edit `analysis-candidate.json` or its repetitions block after freezing.

## Phase 3: Independent Semantic Audit

9. Dispatch a semantic-audit child different from both the parent and the grammar child:

```text
Read and follow <grammar-skill>\references\semantic-audit-contract.md (do not waste context reading SKILL.md).
You are the independent semantic auditor. You must NOT alter the candidate or translation.
1. Run audit_summary.py to inspect blocks, frozen translations, synthesized meanings, phrases, and grammar notes in one summary table and pre-populate semantic-audit.json:
   python -X utf8 <grammar-skill>\scripts\audit_summary.py "<workdir>" --emit-template "<workdir>\semantic-audit.json" --learner-language "<target>" --replace
2. Review the 1-page alignment table printed to stdout:
   - Check accuracy of block meanings, phrase glosses/explanations, and grammar notes against the frozen translation and source lines.
   - Verify educational value and absence of unsupported additions or shared semantic drift.
   - If findings exist, document them accurately in semantic-audit.json; otherwise keep the emitted passing report.
3. Run validate_audit.py to self-verify your audit report conforms to schema:
   python -X utf8 <grammar-skill>\scripts\validate_audit.py "<workdir>\analysis-candidate.json" --candidate-hash "<workdir>\analysis-candidate.sha256" --learner-language "<target>" "<workdir>\semantic-audit.json"
```

10. After the semantic-audit child completes, verify the audit passes:

```powershell
python <grammar-skill>\scripts\validate_audit.py `
  "<workdir>\analysis-candidate.json" `
  --candidate-hash "<workdir>\analysis-candidate.sha256" `
  --learner-language "<target>" `
  "<workdir>\semantic-audit.json"
```

11. Record the semantic-audit child identity:

```powershell
python <grammar-skill>\scripts\record_isolation.py "<workdir>" `
  --stage semantic-audit `
  --child-transcript-id "<actual-audit-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

## Phase 4: Finalize and Validate

12. Run the deterministic finalizer:

```powershell
python <grammar-skill>\scripts\finalize.py "<song.lrc>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<target>"
```

The finalizer requires:

- unchanged source projection and frozen translation;
- draft-bound grammar proof;
- unchanged candidate hash;
- passing audit bound to that candidate;
- audit-bound different-child proof;
- v2 isolation proofs and matching source projection hashes.

Only after every check does it atomically write the sibling JSON.

13. Verify the result, complete chain, and automatically delete `<workdir>` (`<song>.grammar-work`) upon passing:

```powershell
python <grammar-skill>\scripts\validate_all.py `
  "<song.lrc>" "<song.json>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<target>" `
  --cleanup-workdir
```

Report the final path, validation status, and confirm `<workdir>` was cleaned up.

## Batch Execution Mode

Automatically activate batch execution mode whenever the user requests translating or generating sidecars for an entire directory or folder (e.g., "翻译某个文件夹下的所有文件", "批量翻译", "translate all files in directory"), or when scanning a path reveals multiple `.lrc` files.

### 1. Batch Translation Orchestration (Phase 1)

1. Scan the target directory and collect all candidate `.lrc` files, excluding temporary files and `.grammar-work` directories. Identify files that are already bilingual vs. files requiring translation.
2. Run batch source projection upfront (`project_source.py "<song1.lrc>" "<song2.lrc>" ...`) so every song's `<workdir>\source-projection.json` exists before translation starts, then run `lrc_strip.py` for songs requiring translation.
3. For files requiring translation, operate via the **Sliding-Window Concurrency Pool (Worker Pool)**:
   - Maintain up to 3–4 concurrent song translation pipelines.
   - For each song, dispatch the dedicated Stage 1 Translator Child, followed by the Stage 2 Adversarial Reviewer Child in a fresh context, and finalize with Stage 3 Arbiter merge via `lrc_merge.py`.
   - Never bundle multiple songs into a single child prompt — enforce per-song context isolation to eliminate style bleeding and reviewer attention dilution.
4. After all translations pass `lrc_merge.py` with `[OK]`, execute deterministic batch freezing:

```powershell
python <grammar-skill>\scripts\verify_translation.py --batch "<song1.lrc>" "<song2.lrc>" ...
```

### 2. Per-Song Isolated Analysis and Audit (Phase 2 & 3)

Deep grammar analysis and semantic auditing cannot be grouped into a single multi-song prompt because Schema v2 isolation proofs (`isolation-grammar-analysis.json`, `isolation-semantic-audit.json`) are cryptographically bound to each song's `sourceProjectionHash` and distinct non-forked `childTranscriptId`. Furthermore, cross-song bundling causes context degradation and span hallucinations.

1. **Concurrency Sliding Window (Worker Pool)**: Maintain a pool of up to 3–4 concurrent song pipelines (dispatch a new child as soon as a previous one finishes). Do not launch unbounded concurrent children (e.g., 8+ at once) to avoid triggering API rate limits or `RESOURCE_EXHAUSTED (code 429)`. For each song, dispatch a fresh grammar child and a separate fresh semantic-audit child using the standard single-song contracts.
2. **Batch Progress Inspection**: Run `python <grammar-skill>\scripts\status.py "<target-dir>"` at any time to inspect batch progress across all phases or resume seamlessly after interruption.
3. After grammar children complete drafting and isolation proofs are recorded, run candidate preparation in batch:

```powershell
python <grammar-skill>\scripts\prepare.py "<song1.lrc>" "<song2.lrc>" ... --learner-language "<target>"
```

4. Dispatch independent semantic audit children per song. Each auditor verifies the frozen candidate against original and translated LRCs, writes `semantic-audit.json`, and validates the report. Record the audit isolation proof via `record_isolation.py`.

### 3. Batch Finalize and Verification (Phase 4)

Once all songs have verified audits and recorded isolation proofs, finalize all sidecars and validate them atomically in batch:

```powershell
python <grammar-skill>\scripts\finalize.py "<song1.lrc>" "<song2.lrc>" ... --learner-language "<target>"
python <grammar-skill>\scripts\validate_all.py --batch "<song1.lrc>" "<song2.lrc>" ... --learner-language "<target>" --cleanup-workdir
```

**Deterministic No-Read Validation**: Because `finalize.py` and `validate_all.py` enforce 100% cryptographic hash chaining, schema validity, and isolation verification, console output of `[PASS]` / `[OK]` with exit code 0 is authoritative. Do not re-read generated `.json` files into context.

Emit an aggregated status table summarizing the batch execution results:

| Song ID | Source Lines | Translation | Repetition Groups | Semantic Audit | Sidecar Output |
| :-- | :-- | :-- | :-- | :-- | :-- |
| `<song1>` | `<count>` | `[OK]` | `<groups>` | `pass` | `<song1>.json` |
| `<song2>` | `<count>` | `[OK]` | `<groups>` | `pass` | `<song2>.json` |

## Milestone Progress Visibility

Because grammar analysis and semantic audit are in-depth multi-minute tasks, the parent agent should emit a concise single-line milestone progress message to the user at each transition:

- **Phase 1 complete**: Translation accepted and frozen to `<workdir>\translated.lrc`.
- **Phase 2 complete**: Semantic draft authored and candidate frozen to `<workdir>\analysis-candidate.json`.
- **Phase 3 complete**: Semantic audit verified with `status: "pass"`.
- **Phase 4 complete**: Atomic finalization finished, full sidecar chain verified, and `<workdir>` automatically removed.

## Boundaries

- `<skills>` contains this Skill, `lyrics-translator`, and `lyrics-grammar-sidecar`.
- Translation remains byte-for-byte owned by `lyrics-translator` when translation is needed; it is not a runtime dependency of the Sidecar.
- Grammar semantics are authored by the fresh grammar child.
- Semantic approval is owned by the different fresh audit child, never the grammar child or parent.
- Deterministic scripts own Schema v2, repetition discovery/completion, source/span validation, hash chaining, isolation verification, and atomic writes.
- No v1 fallback, migration, or dual read exists.
