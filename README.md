# make-skills

Reusable, user-invoked skills for bilingual lyric translation and timestamp-free Schema v3 lyrics grammar sidecar generation.

## Skills Overview

- **`skills/sakurauta-lyrics-workflow/SKILL.md`**: End-to-end orchestrator connecting `lyrics-translator` (Single-Draft 3-Stage Translation) -> pure-content bilingual handoff & occurrence-ordered `.lrc` merge -> `lyrics-grammar-sidecar` (isolated grammar authoring, independent semantic audit, atomic finalization).
- **`skills/lyrics-translator/SKILL.md`**: Standalone high-fidelity lyric translator across global languages using a Single-Draft Adversarial 3-Stage Pipeline (`roles/translator.md` -> isolated `roles/reviewer.md` -> `roles/arbiter.md`) and deterministic `.lrc` strip/merge scripts.
- **`skills/lyrics-grammar-sidecar/SKILL.md`**: Produces validated, timestamp-free Schema v3 grammar analysis sidecar JSON files (`<song>.json`) from `<workdir>/bilingual-lyrics.json` + `<workdir>/blocks-plan.json` or external bilingual `.lrc` files.

## Pipeline Architecture

```text
<song.lrc>
  -> lrc_strip.py + extract_bilingual.py --emit-index   (<song.lrc>.tmp.txt + <workdir>/lyric-index.txt)
  -> Stage 1 Translator   (roles/translator.md: draft .tmp.txt + proposed stanza groupings)
  -> Stage 2 Reviewer     (roles/reviewer.md: isolated adversarial falsification review)
  -> Stage 3 Arbiter      (roles/arbiter.md: final .tmp.txt + sole author of blocks-plan.json; stops before merge)
  -> extract_bilingual.py (exports timestamp-free <workdir>/bilingual-lyrics.json)
  -> lrc_merge.py         (occurrence-ordered merge into <song.lrc> & deletes .tmp.txt)
  -> verify_translation.py (freezes bilingual-lyrics.frozen.json + translation-manifest.json)
  -> Grammar Child        (scaffold_draft -> enrichment.json -> resolve_spans -> discover_repetitions)
  -> record_isolation.py (--stage grammar-analysis) -> prepare.py
  -> Audit Child          (distinct child: audit_summary --emit-template [pending] -> fill report -> validate_audit --check-format)
  -> record_isolation.py (--stage semantic-audit) -> validate_audit.py (--bilingual + --isolation)
  -> finalize.py -> validate_all.py (--cleanup-workdir [--archive-proofs <dir>])
```

## Discovery

- Main workflow: `skills/sakurauta-lyrics-workflow/SKILL.md`
- Translator skill: `skills/lyrics-translator/SKILL.md`
- Grammar sidecar skill: `skills/lyrics-grammar-sidecar/SKILL.md`
- Schemas (`schema/v3/`): `lyrics-grammar-analysis.schema.json`, `bilingual-lyrics.schema.json`, `isolation-proof.schema.json`, `repetition-candidates.schema.json`, `semantic-audit.schema.json`
- Contracts: `skills/lyrics-grammar-sidecar/references/draft-contract.md`, `skills/lyrics-grammar-sidecar/references/semantic-audit-contract.md`
- Fixtures: `skills/lyrics-grammar-sidecar/fixtures/`

## Verification

Python 3.10+ standard library only:

```powershell
python -X utf8 skills\lyrics-grammar-sidecar\scripts\selftest.py
```

Markdown formatting (Prettier):

```powershell
npm run format:md
npm run check:md
```
