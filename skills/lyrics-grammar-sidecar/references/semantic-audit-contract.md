# Schema v3 Semantic Audit & Isolation Contract

Audit Child must run as an independent fresh subagent with a `childTranscriptId` distinct from Grammar Child. Pass only `bilingual-lyrics.frozen.json`, `analysis-candidate.json`, `analysis-candidate.sha256`, and this contract — never pass Grammar Child's authoring transcript.

## 1. Generate Audit Summary & Pending Template

Run `audit_summary.py` to print every block, frozen line translation, `meaningUnit`, phrase, grammar note, any `excludedRepetitions`, and pre-audit diagnostics, while emitting a **`status: "pending"`** template to `<workdir>/semantic-audit.json`:

```powershell
python -X utf8 "<grammar-skill>/scripts/audit_summary.py" "<workdir>" --emit-template "<workdir>/semantic-audit.json" --replace
```

- When `--replace` overwrites an earlier completed report (`pass` or `fail`), `audit_summary.py` automatically archives the previous report into `<workdir>/audit-history/semantic-audit-rNN-<hash8>.json` so audit history is never lost.
- The emitted template intentionally starts with `"status": "pending"`, `"reviewedBlockIds": []`, and `"reviewedMeaningUnitIds": []` so an unedited template cannot pass validation.

## 2. Independent Semantic Checks

Compare every block and entity in `analysis-candidate.json` against `bilingual-lyrics.frozen.json`:

- **Meaning fidelity & completeness (`unsupported-addition` / `translation-mismatch` / `coverage-gap`)**: Verify every `meaningUnit.text`, assembled `block.meaning.parts`, and `grammarNote` covers **every single line** in the block (paying special attention to opening/closing lines and any `[WARN] Possible omitted line` diagnostic) without hallucinated imagery, dropped clauses, tense reversals, ungrounded pronoun shifts (such as injecting plural `"我们"` for Japanese volitional `〜おう/〜よう` when the lyric persona is singular `"我"`), or duplicate boundary punctuation.
- **Repetition consistency & exclusions (`shared-drift`)**: Verify shared `meaningUnits` and `phrases` across `repetitionGroups` preserve consistent meaning or justify nuance shifts with a truthful `semanticOverride.reason`. If `extensions.excludedRepetitions` is non-empty, verify each excluded candidate is genuinely a spurious fragment rather than a real repeated lyric hook.
- **Grounding & clean prose (`missing-source-evidence`)**: Confirm every phrase, relation, and `grammarNote` matches actual `sourceSegments`, uses `learnerLanguage`, and contains zero HTML/XML tags, file paths, or timeline/file metadata leakage.

## 3. Fill `semantic-audit.json` & Run Stage A Self-Check

Update `<workdir>/semantic-audit.json` (`schema: "sakurauta.lyrics-grammar-semantic-audit"`, `auditVersion: 1`) with every reviewed `blockId` and `meaningUnitId`, any `findings`, and `status: "pass"` (only if zero `error` findings) or `"fail"` (at least one `error` finding):

```json
{
  "schema": "sakurauta.lyrics-grammar-semantic-audit",
  "auditVersion": 1,
  "candidateSha256": "<exact hash from analysis-candidate.sha256>",
  "learnerLanguage": "zh-CN",
  "status": "pass",
  "reviewedBlockIds": ["b_01", "b_02"],
  "reviewedMeaningUnitIds": ["mu_b_01", "mu_b_02"],
  "findings": []
}
```

Valid finding `code` values: `unsupported-addition`, `translation-mismatch`, `shared-drift`, `coverage-gap`, `missing-source-evidence`, `other`, with `severity: "error" | "warning"`.

### Two-Stage `validate_audit.py` Contract

1. **Stage A — Audit Child self-check (BEFORE `record_isolation.py`)**: Run `validate_audit.py` **without** `--bilingual` and **without** `--isolation`, passing `--check-format` so both valid `"pass"` and valid `"fail"` reports (with error findings) confirm schema, candidate hash, and 100% block/MU coverage while rejecting `"pending"`:

   ```powershell
   python -X utf8 "<grammar-skill>/scripts/validate_audit.py" "<workdir>/analysis-candidate.json" --candidate-hash "<workdir>/analysis-candidate.sha256" "<workdir>/semantic-audit.json" --learner-language "<target>" --check-format
   ```

2. **Stage B — Orchestrator full gate (AFTER `record_isolation.py --stage semantic-audit`)**: The orchestrator records `isolation-semantic-audit.json` (which binds `contentHash`, `artifactSha256`, and distinct `childTranscriptId`) and then runs `validate_audit.py` **with both `--bilingual` and `--isolation`** and **without `--check-format`** (requiring `status: "pass"` before `finalize.py`). Passing only one of `--bilingual` or `--isolation` fails with `incomplete_audit_inputs`.

## 4. Revision Loop Cap

If Stage A finishes with `status: "fail"`, return all findings together so Grammar Child fixes every finding in a single batched revision pass before re-running `prepare.py` and a second Audit Child pass. Do not run more than 2 audit rounds without escalating to the user.
