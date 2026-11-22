---
name: lyrics-grammar-sidecar
description: Generate, validate, audit, and finalize SakuraUta Schema v2 lyrics grammar sidecars from local LRCs, frozen bilingual LRCs, deterministic repetition candidates, and independent semantic-audit children. Supports single-file and directory-wide batch processing.
metadata:
  version: "2.2.3"
---

# Lyrics Grammar Sidecar v2

This Skill is self-contained. Its schemas live under `schema/v2/`, scripts under `scripts/`, and authoring/audit contracts under `references/`. Do not depend on a repository root or developer machine path.

Schema v1 is unsupported. Do not dual-read, migrate, adapt, or fall back.

## Roles and Boundary

The overall workflow uses up to three fresh child roles:

1. translate only when the source LRC is not already an accepted bilingual LRC; the unchanged `lyrics-translator` Skill is the default translator, not a runtime dependency;
2. analyze grammar in a fresh grammar child;
3. audit semantics in a different fresh audit child.

The grammar child writes only `semantic-draft.json`. The deterministic candidate tool may write `repetition-candidates.json`; `prepare.py` writes the candidate and its hash.

The audit child writes only `semantic-audit.json`. It cannot edit the candidate or draft.

Only `finalize.py` writes the production sibling `<song>.json`.

## Required Inputs

- original local `.lrc`;
- an accepted bilingual `.lrc` (any provenance; it may already be the original file or an alternate path);
- `<song>.grammar-work/source-projection.json`;
- frozen `<song>.grammar-work/translated.lrc` plus `translation-manifest.json` (the freeze is an audit snapshot, not a distribution requirement);
- target learner language, for example `zh-CN`;
- real non-forked transcript IDs for grammar analysis and semantic audit.

Reject video, subtitle, remote, network-share, non-LRC, and symlinked source inputs.

## Grammar-only and Distribution

- If `<song>.lrc` already contains an accepted translation, skip the translation child and start at source projection. If no accepted bilingual LRC exists, stop and ask for translation; do not invent learner-facing meaning from source-only lyrics.
- The production `<song>.json` is self-contained. A recipient only needs a sibling LRC whose NFC source text order matches the analyzed source. Timestamps may differ; the App re-anchors by text. Translation rows and `.grammar-work` are not required for distribution.
- Keep `source.lrcProjectionHash` as exact/provenance metadata. It is not the consumer's availability gate.

## 1. Project the Source

```powershell
python scripts\project_source.py "<song.lrc>" `
  --song-id "<SakuraUta songId>"
```

Default output: `<song-dir>/<song>.grammar-work/source-projection.json`.

The projection owns line IDs, source order, timestamps, fingerprints, source text, and the projection hash. Later stages may not rewrite them.

The grammar projection keeps timed title/artist header rows (for example `[00:00.00]Song - Artist`) and excludes credit rows, empty rows, and non-timed tags. This matches the App's grammar projection. The App's scrolling lyrics / indexing parser still hides title and credit rows from the lyric display.

## 2. Freeze the Accepted Translation

When translation is needed, it is produced by the unchanged `lyrics-translator` Skill on `<song.lrc>`. If an accepted bilingual LRC already exists, freeze that path directly. After the user accepts it:

```powershell
python scripts\verify_translation.py `
  "<workdir>\source-projection.json" `
  "<song.lrc>" `
  --workdir "<workdir>"
```

This writes `translated.lrc` and `translation-manifest.json`. (If an alternate accepted bilingual path was used, pass that instead). A later edit fails closed.

`translated.lrc` / `translation-manifest.json` bind the grammar and audit children to one reviewed snapshot. They do not bind the production Sidecar to the recipient's LRC.

## 3. Fresh Grammar Child

Give the grammar child:

- the original LRC;
- source projection;
- frozen `translated.lrc`;
- requested learner language;
- [references/draft-contract.md](references/draft-contract.md).

The grammar child authors only `semantic-draft.json` following this fast, token-efficient 3-step workflow:

### Step 3.1: Scaffolding the Baseline Draft

Run `scripts\scaffold_draft.py` to automatically scaffold a Schema v2 compliant initial draft with lines, monotonic blocks, pre-synthesized meanings from `translated.lrc`, and exact repetition groups:

```powershell
python scripts\scaffold_draft.py "<workdir>" `
  --learner-language "<learner language>" `
  --auto-repetitions
```

This deterministic tool creates all baseline lines and blocks, aligns translation text, and discovers repetition candidates. **Agents must not hand-author 2,000+ lines of structural JSON or reverse-engineer internal python scripts (`v2lib.py`, `sidecarlib.py`, etc.).**

### Step 3.2: Enrich Phrases and Grammar Notes

The grammar child enriches `semantic-draft.json` by adding high-value educational items:

- `phrases`: Key vocabulary, idioms, compound expressions, or verb phrases with translations and grammatical labels.
- `grammarNotes`: In-depth explanations of grammatical constructs, nuances, particle functions, or stylistic features.

### Step 3.3: Resolve Spans and Validate

Run `scripts\resolve_spans.py` to automatically compute and fix Unicode code-point spans for all added phrases and notes:

```powershell
python scripts\resolve_spans.py `
  "<workdir>\semantic-draft.json" `
  --projection "<workdir>\source-projection.json" `
  --in-place
```

Verify that the draft passes all Schema v2 rules:

```powershell
python -X utf8 scripts\validate.py `
  "<workdir>\semantic-draft.json" `
  --projection "<workdir>\source-projection.json" `
  --learner-language "<learner language>"
```

After the child returns and the draft is final, the parent records the actual grammar-child identity:

```powershell
python scripts\record_isolation.py "<workdir>" `
  --stage grammar-analysis `
  --child-transcript-id "<actual-grammar-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

Positional argument accepts `<workdir>`, `<song.lrc>`, or `<projection.json>`. Artifact, output, and method (`native-subagent`) are automatically inferred when pointing to a workdir or LRC file. Explicit paths remain supported. Never invent transcript IDs. Inline or forked execution is rejected.

## 4. Freeze the Analysis Candidate

The parent runs the deterministic freeze after recording the grammar proof:

```powershell
python scripts\prepare.py "<song.lrc>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<learner language>"
```

Preparation verifies:

- source projection still matches the original LRC;
- translation freeze is intact;
- Schema v2 and learner language are valid;
- source fields normalize exactly from the projection;
- every discovered repetition candidate is present and exact;
- meaning parts cover every block line;
- shared phrase/meaning occurrences map at identical canonical offsets.

Outputs:

- `analysis-candidate.json`;
- `analysis-candidate.sha256`;
- `repetition-candidates.json`;
- `validation-report.json`.

If preparation fails, revise the semantic draft in a fresh grammar child. Do not edit the frozen translation or hand-edit the candidate.

## 5. Different Fresh Semantic-Audit Child

Dispatch a fresh child whose transcript differs from the grammar child and parent. Give it the original LRC, frozen translation, candidate, candidate hash, read-only semantic draft for supporting context, and [references/semantic-audit-contract.md](references/semantic-audit-contract.md).

The audit child writes only `semantic-audit.json` following this fast, token-efficient workflow:

### Step 5.1: Generate Summary and Audit Template

Run `scripts\audit_summary.py` to inspect the candidate against frozen translations and pre-populate `semantic-audit.json` with all reviewed block and meaning unit IDs:

```powershell
python scripts\audit_summary.py "<workdir>" `
  --emit-template "<workdir>\semantic-audit.json" `
  --learner-language "<learner language>" `
  --replace
```

This prints a concise 1-page alignment table of blocks, lines, translations, and synthesized meanings to stdout and pre-populates `semantic-audit.json` with `status: "pass"`. **The audit child must not dump thousands of lines of candidate JSON into context or write temporary python scripts.**

### Step 5.2: Evaluate and Report

Review the concise summary printed to stdout for:

1. Unsupported additions (e.g. newly invented motives, scenes, relationships not in translation);
2. Translation mismatches (effective block meaning deviating from accepted translation);
3. Shared semantic drift across identical occurrences;
4. Coverage gaps (uncovered lines or tails).

- **If the candidate is faithful and accurate**: The pre-populated report is already valid and ready.
- **If findings exist**: Edit `<workdir>\semantic-audit.json` to set `"status": "fail"` and append structured finding objects to `findings: [...]`.

### Step 5.3: Self-Verify

Validate the report:

```powershell
python scripts\validate_audit.py `
  "<workdir>\analysis-candidate.json" `
  --candidate-hash "<workdir>\analysis-candidate.sha256" `
  --learner-language "<learner language>" `
  "<workdir>\semantic-audit.json"
```

After validation, the parent records the audit-child proof:

```powershell
python scripts\record_isolation.py "<workdir>" `
  --stage semantic-audit `
  --child-transcript-id "<actual-audit-child-id>" `
  --parent-transcript-id "<actual-parent-id>" `
  --replace
```

An audit `fail`, error finding, missing reviewed ID, candidate-hash mismatch, same-child self-audit, or v1 proof blocks finalization.

## 6. Finalize

The parent runs the deterministic finalizer:

```powershell
python scripts\finalize.py "<song.lrc>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<learner language>"
```

The finalizer rechecks the full chain:

```text
source projection
  -> semantic-draft.json
  -> analysis-candidate.json
  -> semantic-audit.json
  -> isolation proofs(stage, artifactSha256)
  -> final <song>.json
```

It atomically writes:

```text
dirname(lrc) / basename(lrc, ".lrc") + ".json"
```

Existing differing output is preserved unless the user explicitly passes `--replace`. An existing Schema v1 production file must be regenerated with `--replace`; there is no v1 read or migration path.

Then validate the production result and chain:

```powershell
python scripts\validate_all.py `
  "<song.lrc>" "<song.json>" `
  --projection "<workdir>\source-projection.json" `
  --workdir "<workdir>" `
  --learner-language "<learner language>"
```

## Batch Operations

The deterministic CLI tools natively support batch execution across multiple songs:

- **Batch Progress Inspection**:

```powershell
python scripts\status.py "<target-dir>"
```

Inspects all `.lrc` files in the target directory, checks presence and validity of projections, translations, drafts, isolation proofs, candidates, audits, and final JSON sidecars, and displays a formatted progress table showing the next required action per song.

Completed rows report `Complete (Valid)` only after the final sidecar passes deterministic validation; otherwise the action is `Review: <error-code>`.

- **Batch Source Projection**:

```powershell
python scripts\project_source.py "<song1.lrc>" "<song2.lrc>" ...
```

Derives `songId` from each file's stem and writes to `<song>.grammar-work\source-projection.json`.

- **Batch Translation Freeze**:

```powershell
python scripts\verify_translation.py --batch "<song1.lrc>" "<song2.lrc>" ...
```

Verifies bilingual LRC content against each song's source projection and writes `translated.lrc` and `translation-manifest.json` in each song's work directory.

- **Batch Candidate Preparation**:

```powershell
python scripts\prepare.py "<song1.lrc>" "<song2.lrc>" ... --learner-language "<learner language>"
```

Validates projections, schemas, repetitions, and mappings across all songs, generating candidates and hashes in their respective work directories.

- **Batch Finalization**:

```powershell
python scripts\finalize.py "<song1.lrc>" "<song2.lrc>" ... --learner-language "<learner language>"
```

Atomically produces sibling `<song>.json` for each song passing full cryptographic and audit chain checks.

- **Batch Complete Validation**:

```powershell
python scripts\validate_all.py --batch "<song1.lrc>" "<song2.lrc>" ... --learner-language "<learner language>"
```

Verifies the production artifacts and complete audit chains across all songs, returning exit code 0 on complete batch success.

### 2. No-Read Verification Principle (免读验证原则)

All deterministic stage tools (`verify_translation.py`, `prepare.py`, `validate_audit.py`, `finalize.py`, `validate_all.py`) execute mathematically complete validation across schemas, line counts, timestamps, hashes, Unicode spans, and isolation proofs:

- When a tool exits with code 0 and prints `[OK]` or `[PASS]`, the output artifact is 100% verified.
- **Agents must not invoke file-reading tools (`read_file`, etc.) to re-read or inspect generated `.lrc` or `.json` files**, conserving massive context tokens and execution latency.

### 3. Concurrency and Cryptographic Isolation

- **Concurrency**: Orchestrators may run up to 5 concurrent song pipelines in parallel.
- **Strict Per-Song Isolation**: Every song must retain its own fresh non-forked grammar child and a separate fresh non-forked audit child. Schema v2 cryptographic isolation proofs (`sourceProjectionHash`, `candidateHash`, `childTranscriptId`) are strictly song-bound and cannot be combined across songs.

## Validation Boundary

Deterministic validation owns:

- Schema v2 and v1 rejection;
- strict UTF-8 JSON with duplicate-key, non-finite-number, and surrogate rejection;
- source identity and projection hashes;
- Unicode code-point spans and contiguous occurrence mapping;
- exact NFC repetition discovery and candidate completion;
- canonical occurrence inheritance and explicit override structure;
- composed meaning coverage and boundary punctuation;
- references, multi-block scopes, learner language, HTML/path guards;
- candidate/audit/proof hash chain and atomic writes.
- source-order monotonic blocks; block member timestamps may be non-monotonic after user timeline calibration, and block start/end are the member minimum/maximum.

It does not decide whether prose is faithful. That is the independent audit child's responsibility. The generation child must never self-approve its own semantic audit.

Sidecars that fail with `duplicate_boundary_punctuation` must be revised in a fresh grammar child and re-audited; do not patch `analysis-candidate.json` or the production JSON.

## Self-Test

Run from any current directory:

```powershell
python scripts\selftest.py
```

The standard-library-only suite generates every prepare -> audit -> finalize chain in a temporary workdir. Its only committed repetition case is the compact `fixtures/repetition` input set (source LRC, accepted translation, semantic draft, and final sidecar golden), so candidate, audit, isolation-proof, and validation-report copies are not duplicated in the repository. Fixture LRC inputs are committed as `.txt` so distribution platforms that reject `.lrc` uploads can still carry the suite; the tests stage them to temporary `.lrc` files before parsing. Coverage includes exact maximal and changed-tail repetition, three occurrences, overlap, line-break variation, cross-line NFC composition, internal whitespace, fuzzy non-matches, metadata exclusion, missing/wrong shared occurrences, blank overrides, meaning coverage, boundary punctuation, strict JSON, path and HTML guards, audit pass/fail, proof/hash/canonical-byte tamper, v1 rejection, and atomic finalization.
