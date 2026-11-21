---
name: sakurauta-lyrics-workflow
description: Create bilingual LRC translations and SakuraUta Schema v2 grammar-analysis sidecars. Coordinates fresh child roles for translation, grammar analysis, and independent semantic audit; deterministic scripts freeze and finalize the contract. Automatically activates batch workflow when a directory or multiple LRC files are specified or discovered.
version: 2.2.1
---

# SakuraUta Lyrics Workflow v2

The parent coordinates three independent child roles. It does not translate, invent grammar analysis, or self-audit semantics inline.

1. Translation child: reads `lyrics-translator` directly.
2. Grammar child: authors only the v2 semantic draft. A deterministic tool writes its repetition-candidate list, and the parent freezes the candidate.
3. Semantic-audit child: a different fresh transcript that reviews the frozen candidate and writes only the audit report.

Only the deterministic finalizer writes `<song>.json`.

## Inputs

- local source `.lrc`;
- target learner language, for example `zh-CN`;
- SakuraUta `songId` (default: LRC basename without `.lrc`).

Work directory: `<song>.grammar-work` beside the source.

Quote all file paths in PowerShell commands (especially when titles contain special characters like semicolons `;`, ampersands `&`, dollars `$`, or apostrophes `'`).

Reject video, subtitle, remote, non-LRC, network-share, and symlinked inputs.

## Isolation Gate

A child is a fresh non-forked sub-agent or a fresh independent CLI transcript. Loading a Skill into the parent is not isolation.

The grammar and semantic-audit children must have different `childTranscriptId` values. When the harness exposes parent IDs, both children must also differ from the parent. If separate contexts are unavailable, stop with:

```text
ERROR [isolation-unavailable]
```

Never fall back to inline translation, grammar analysis, or self-audit.

## Phase 1: Translate and Freeze

1. Dispatch a fresh translation child (skip if `<song.lrc>` is already bilingual and accepted):

```text
Read and follow <skills>\lyrics-translator\SKILL.md.
Translate <song.lrc> into <target learner language>.
Do not produce grammar JSON.
```

The translation child must strictly follow `lyrics-translator`: run `lrc_strip.py` to produce a timestamp-free plain text working file, translate in plain text without timestamp distraction, and run `lrc_merge.py` to merge translations into `<song.lrc>`. Do not add a translation wrapper Skill, do not expose `<workdir>` or projection internals to the translation child, and do not restate the translator's quality rules.

2. Create the source projection:

```powershell
python <grammar-skill>\scripts\project_source.py "<song.lrc>" `
  --song-id "<songId>"
```

`project_source.py` canonicalizes the source rows (automatically ignoring interleaved translation rows if present) and writes `<workdir>\source-projection.json`.

3. After the user accepts the translation, freeze it:

```powershell
python <grammar-skill>\scripts\verify_translation.py `
  "<workdir>\source-projection.json" `
  "<song.lrc>" `
  --workdir "<workdir>"
```

This verifies the bilingual handoff in `<song.lrc>` against the source projection, freezes a snapshot to `<workdir>\translated.lrc`, and writes `translation-manifest.json`. (If the accepted translation resides in an alternate file, pass that path as `<accepted-lrc>` instead). The parent owns acceptance. Do not proceed if freezing fails. Do not edit `translated.lrc` after this point.

## Phase 2: Fresh Grammar Analysis

4. Dispatch a grammar child different from the parent:

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

5. After the grammar child returns, record the actual grammar-child identity:

```powershell
python <grammar-skill>\scripts\record_isolation.py "<workdir>" `
  --stage grammar-analysis `
  --child-transcript-id "<actual-grammar-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

Never invent an ID. Explicit file paths remain supported.

6. Deterministically freeze the candidate:

```powershell
python <grammar-skill>\scripts\prepare.py "<song.lrc>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<target>"
```

This validates projection/freeze identity, Schema v2, exact repetition completion, canonical source normalization, meaning coverage, boundary punctuation, and shared occurrence mappings. It writes:

- `analysis-candidate.json`;
- `analysis-candidate.sha256`;
- `repetition-candidates.json`;
- `validation-report.json`.

If preparation fails, rerun grammar analysis in a new fresh transcript. Do not patch the candidate or translation.

## Phase 3: Independent Semantic Audit

7. Dispatch a different fresh child:

```text
Read and follow <grammar-skill>\references\semantic-audit-contract.md.
Step 1: Run audit_summary.py to inspect the candidate against frozen translations and emit the pre-populated audit template:
  python scripts\audit_summary.py "<workdir>" --emit-template "<workdir>\semantic-audit.json" --learner-language "<target>"
Step 2: Check the printed summary for meaning fidelity, unsupported additions, translation mismatches, or coverage gaps.
  - If all candidate blocks and meaning units faithfully reflect the translation: the pre-populated template is already set to status "pass".
  - If there are errors/warnings: edit <workdir>\semantic-audit.json to set status "fail" and add specific finding objects to findings.
Step 3: Self-verify the report before returning:
  python scripts\validate_audit.py "<workdir>\analysis-candidate.json" --candidate-hash "<workdir>\analysis-candidate.sha256" "<workdir>\semantic-audit.json" --learner-language "<target>"
STRICT RULES:
- Do not inspect or read internal scripts (v2lib.py, sidecarlib.py, etc.) or write scratch Python scripts.
- Do not dump full LRC or JSON files into context.
- Write only <workdir>\semantic-audit.json. Do not edit draft, candidate, hash, translation, or final sidecar.
- Do not write isolation-semantic-audit.json (the parent records isolation proofs).
```

The audit must review every candidate block and meaning-unit ID. It must reject unsupported additions, translation mismatches, shared semantic drift, coverage gaps, and missing source evidence.

8. Validate the audit report:

```powershell
python <grammar-skill>\scripts\validate_audit.py `
  "<workdir>\analysis-candidate.json" `
  --candidate-hash "<workdir>\analysis-candidate.sha256" `
  --learner-language "<target>" `
  "<workdir>\semantic-audit.json"
```

9. After validating the report, record the actual audit-child identity:

```powershell
python <grammar-skill>\scripts\record_isolation.py "<workdir>" `
  --stage semantic-audit `
  --child-transcript-id "<actual-audit-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

This ID must differ from `<actual-grammar-child-id>`. A same-child audit is always rejected. Explicit file paths remain supported.

If the audit fails, do not finalize. Rerun analysis and audit in fresh transcripts after resolving the finding, or ask the user to resolve the semantic dispute.

## Phase 4: Finalize and Verify

10. Run the deterministic finalizer:

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

11. Verify the result and complete chain:

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

1. Scan the target directory and collect all candidate `.lrc` files, excluding temporary files and `.grammar-work` directories.
2. Partition the files into batches of up to 5 files each, maintaining up to 5 concurrent translation subagents (`invoke_subagent`).
3. Each translation subagent receives the standardized prompt enforcing the three core constraints:
   - **Mandatory Full Skill Execution**: The subagent must first completely read and strictly follow `lyrics-translator`'s `SKILL.md` and all referenced rules (`reference/common.md` semantic chunking, `source/`, `target/`, and `pair-exceptions.md`). Cutting corners or literal line-by-line direct translation is strictly forbidden.
   - **Efficient Batching & No-Read Verification Principle (免读验证原则)**:
     - Run `python <translator-skill>\scripts\lrc_strip.py <file1> <file2>...` to batch-strip timestamps into `.tmp.txt` working files.
     - Translate pure lyrics in plain text within each `.tmp.txt` file without timestamp distractions.
     - Run `python <translator-skill>\scripts\lrc_merge.py <file1> <file2>...` to batch-merge and deterministically verify timeline alignment.
     - **No-Read Verification Principle**: `lrc_merge.py` performs strict deterministic line-count, timestamp, and metadata verification. Output of `[OK]` represents 100% verification success. **Subagents and parent agents are strictly forbidden from calling file-reading tools (`read_file`, etc.) to re-read merged `.lrc` files**, saving massive context tokens.
   - **Role Isolation & Autonomous Progression**: Subagents focus solely on translating assigned files without inspecting global configs or unrelated files. The parent coordinates the batch fully autonomously without requiring per-file user confirmation.
4. After all translation subagents finish, execute deterministic batch projection and batch freezing:

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
- Translation remains byte-for-byte owned by `lyrics-translator`.
- Grammar semantics are authored by the fresh grammar child.
- Semantic approval is owned by the different fresh audit child, never the grammar child or parent.
- Deterministic scripts own Schema v2, repetition discovery/completion, source/span validation, hash chaining, isolation verification, and atomic writes.
- No v1 fallback, migration, or dual read exists.
