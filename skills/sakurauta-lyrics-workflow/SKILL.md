---
name: sakurauta-lyrics-workflow
description: "Create bilingual LRC translations and SakuraUta Schema v2 grammar-analysis sidecars. Coordinates fresh child roles for translation (Adversarial 3-Stage Pipeline: Translator → Reviewer in clean context → Arbiter/Merge), grammar analysis, and independent semantic audit; deterministic scripts freeze and finalize the contract. Automatically activates batch workflow when a directory or multiple LRC files are specified or discovered."
metadata:
  version: "2.3.0"
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
- an accepted bilingual `.lrc` (optional; if absent, Phase 1 translation is required);
- target learner language, for example `zh-CN`;
- SakuraUta `songId` (default: LRC basename without `.lrc`).

Work directory: `<song>.grammar-work` beside the source.

Quote all file paths in PowerShell commands (especially when titles contain special characters like semicolons `;`, ampersands `&`, dollars `$`, or apostrophes `'`).

Reject video, subtitle, remote, non-LRC, network-share, and symlinked inputs.

## Grammar-only Mode

Use this mode when the user only wants a grammar Sidecar and already has an accepted bilingual LRC:

1. Skip the translation child entirely.
2. Start at `project_source.py` on the existing `<song>.lrc`.
3. Freeze the accepted bilingual LRC with `verify_translation.py` (pass the alternate path if needed).
4. Continue with grammar analysis, audit, and finalize.

If the LRC is source-only, stop with `ERROR [translation-required]` and ask for a translation. Do not invent learner-facing meaning from source-only lyrics.

## Isolation Gate

A child is a fresh non-forked sub-agent or a fresh independent CLI transcript. Loading a Skill into the parent is not isolation.

The grammar and semantic-audit children must have different `childTranscriptId` values. When the harness exposes parent IDs, both children must also differ from the parent. If separate contexts are unavailable, stop with:

```text
ERROR [isolation-unavailable]
```

Never fall back to inline translation, grammar analysis, or self-audit.

## Phase 1: Translate and Freeze

Execute the Adversarial 3-Stage Translation Pipeline only when `<song.lrc>` is not already bilingual and accepted:

1. **Step 1: Strip Timestamps**:

   ```powershell
   python <translator-skill>\scripts\lrc_strip.py "<song.lrc>"
   ```

   This generates `<song>.tmp.txt` in the same directory. No-Read Principle applies: the parent does not need to read `<song>.tmp.txt` before dispatching Stage 1; exit code 0 is authoritative.

2. **Step 2: Dispatch Translator Child (Stage 1)**:

   ```text
   Read and follow <skills>\lyrics-translator\roles\translator.md and its referenced linguistic profiles in <skills>\lyrics-translator\reference\.
   Translate the working file <song>.tmp.txt into <target learner language>.
   Output ONLY the Song Persona and Theme handover memo upon completion.
   Do NOT dump or print the full translated lyrics in your response (the disk file is authoritative).
   Do not produce grammar JSON.
   ```

3. **Step 3: Dispatch Adversarial Reviewer Child (Stage 2 — Clean Isolated Context)**: Dispatch a **separate, fresh subagent** with zero memory of the translator's thought process:

   ```text
   Read and follow <skills>\lyrics-translator\roles\reviewer.md.
   Audit the draft translation in <song>.tmp.txt against the original source lyrics and the translator's Song Persona handover memo.
   Execute the Adversarial Falsification Protocol:
   - Identify dictionary first-sense traps (e.g., polysemous idioms or rhetorical phrases translated literally).
   - Identify contextual contradictions (emotional or causal breaks with surrounding lines).
   - Identify register collapse or narrative persona drift.
   - Enforce red lines (no plot injection, length within cap, metadata immunity).
   Output your structured critique report according to roles\reviewer.md.
   ```

4. **Step 4: Arbiter & Deterministic Merge (Stage 3)**:
   - Mandatorily adopt all critical defect fixes identified by the Reviewer child; arbitrate stylistic suggestions against the Song Persona.
   - Apply polished lines to `<song>.tmp.txt` in a single write pass or script execution (avoid multi-turn single-line edit calls).
   - Run the deterministic merge script:
     ```powershell
     python <translator-skill>\scripts\lrc_merge.py "<song.lrc>" "<song>.tmp.txt"
     ```
   - Verify the console outputs `[OK]`. (No-Read Verification Principle: do NOT manually re-read the merged `.lrc` file; exit code 0 is authoritative).

5. **Step 5: Create Source Projection**:

   ```powershell
   python <grammar-skill>\scripts\project_source.py "<song.lrc>" `
     --song-id "<songId>"
   ```

   `project_source.py` canonicalizes the source rows (automatically ignoring interleaved translation rows if present) and writes `<workdir>\source-projection.json`.

6. **Step 6: Freeze Accepted Translation**: After the user accepts the translation, freeze it:
   ```powershell
   python <grammar-skill>\scripts\verify_translation.py `
     "<workdir>\source-projection.json" `
     "<song.lrc>" `
     --workdir "<workdir>"
   ```
   This verifies the bilingual handoff in `<song.lrc>` against the source projection, freezes a snapshot to `<workdir>\translated.lrc`, and writes `translation-manifest.json`. (If the accepted translation resides in an alternate file, pass that path as `<accepted-lrc>` instead). The parent owns acceptance. Do not proceed if freezing fails. Do not edit `translated.lrc` after this point. The freeze is an audit snapshot; the production JSON remains self-contained and does not require recipients to ship `.grammar-work`.

## Phase 2: Fresh Grammar Analysis

7. Dispatch a grammar child different from the parent:

```text
Read and follow <grammar-skill>\SKILL.md and <grammar-skill>\references\draft-contract.md.
Step 1: Run scaffold_draft.py to generate the initial compliant draft with lines, monotonic blocks, pre-synthesized meanings, and repetitions:
  python scripts\scaffold_draft.py "<workdir>" --learner-language "<target>" --auto-repetitions
Step 2: Enrich the draft by adding educational phrases and grammarNotes with translations and explanations.
Step 3: Run resolve_spans.py to automatically compute and fix code-point spans:
  python scripts\resolve_spans.py "<workdir>\semantic-draft.json" --projection "<workdir>\source-projection.json" --in-place
Step 4: Verify your draft passes 100% of validation rules:
  python scripts\validate.py "<workdir>\semantic-draft.json" --projection "<workdir>\source-projection.json" --learner-language "<target>"
STRICT RULES:
- Do not inspect or read internal scripts (v2lib.py, sidecarlib.py, etc.) or write scratch Python scripts.
- Do not dump the full LRC or JSON files into context.
- Write only <workdir>\semantic-draft.json. Do not write isolation proofs or <song>.json, and do not alter the frozen translation.
```

8. After the grammar child returns, record the actual grammar-child identity:

```powershell
python <grammar-skill>\scripts\record_isolation.py "<workdir>" `
  --stage grammar-analysis `
  --child-transcript-id "<actual-grammar-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

9. Prepare and freeze the repetition-candidate list deterministically:

```powershell
python <grammar-skill>\scripts\prepare.py "<song.lrc>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<target>"
```

`prepare.py` validates Schema v2 conformance, repetition discovery/completion, and writes `<workdir>\analysis-candidate.json` along with its cryptographic hash `<workdir>\analysis-candidate.sha256`. Do not edit `analysis-candidate.json` or its repetitions block after freezing.

## Phase 3: Independent Semantic Audit

11. Dispatch a semantic-audit child different from both the parent and the grammar child:

```text
Read and follow <grammar-skill>\SKILL.md and <grammar-skill>\references\semantic-audit-contract.md.
You are the independent semantic auditor. You must NOT alter the candidate or translation.
1. Run audit_summary.py to inspect the candidate against frozen translations and pre-populate the audit template:
   python -X utf8 scripts\audit_summary.py "<workdir>" --emit-template "<workdir>\semantic-audit.json" --learner-language "<target>" --replace
2. Review the 1-page alignment table against the frozen translation and candidate:
   - Check accuracy of line and phrase meanings against the frozen translation.
   - Verify educational value of selected grammar points and expressions.
   - If findings exist, document them accurately in semantic-audit.json.
3. Run validate_audit.py to self-verify your audit report conforms to schema:
   python -X utf8 scripts\validate_audit.py "<workdir>\analysis-candidate.json" --candidate-hash "<workdir>\analysis-candidate.sha256" --learner-language "<target>" "<workdir>\semantic-audit.json"
```

12. After the semantic-audit child completes, verify the audit passes:

```powershell
python <grammar-skill>\scripts\validate_audit.py `
  "<workdir>\analysis-candidate.json" `
  --candidate-hash "<workdir>\analysis-candidate.sha256" `
  --learner-language "<target>" `
  "<workdir>\semantic-audit.json"
```

13. Record the semantic-audit child identity:

```powershell
python <grammar-skill>\scripts\record_isolation.py "<workdir>" `
  --stage semantic-audit `
  --child-transcript-id "<actual-audit-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

## Phase 4: Finalize and Validate

14. Run the deterministic finalizer:

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

15. Verify the result and complete chain:

```powershell
python <grammar-skill>\scripts\validate_all.py `
  "<song.lrc>" "<song.json>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<target>"
```

Report the final path and validation status.

## Batch Execution Mode

Automatically activate batch execution mode whenever the user requests translating or generating sidecars for an entire directory or folder (e.g., "翻译某个文件夹下的所有文件", "批量翻译", "translate all files in directory"), or when scanning a path reveals multiple `.lrc` files.

### 1. Batch Translation Orchestration (Phase 1)

1. Scan the target directory and collect all candidate `.lrc` files, excluding temporary files and `.grammar-work` directories. Identify files that are already bilingual vs. files requiring translation.
2. For files requiring translation, operate via the **Sliding-Window Concurrency Pool (Worker Pool)**:
   - Maintain up to 3–4 concurrent song translation pipelines.
   - For each song, dispatch the dedicated Stage 1 Translator Child, followed by the Stage 2 Adversarial Reviewer Child in a fresh context, and finalize with Stage 3 Arbiter merge via `lrc_merge.py`.
   - Never bundle multiple songs into a single child prompt — enforce per-song context isolation to eliminate style bleeding and reviewer attention dilution.
3. After all translations pass `lrc_merge.py` with `[OK]`, execute deterministic batch projection and batch freezing:

```powershell
python <grammar-skill>\scripts\project_source.py "<song1.lrc>" "<song2.lrc>" ...
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
python <grammar-skill>\scripts\validate_all.py --batch "<song1.lrc>" "<song2.lrc>" ... --learner-language "<target>"
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
- **Phase 4 complete**: Atomic finalization finished and full sidecar chain verified.

## Boundaries

- `<skills>` contains this Skill, `lyrics-translator`, and `lyrics-grammar-sidecar`.
- Translation remains byte-for-byte owned by `lyrics-translator` when translation is needed; it is not a runtime dependency of the Sidecar.
- Grammar semantics are authored by the fresh grammar child.
- Semantic approval is owned by the different fresh audit child, never the grammar child or parent.
- Deterministic scripts own Schema v2, repetition discovery/completion, source/span validation, hash chaining, isolation verification, and atomic writes.
- No v1 fallback, migration, or dual read exists.
