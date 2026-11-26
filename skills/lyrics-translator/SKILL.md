---
name: lyrics-translator
description: High-fidelity lyric translation across global languages (dedicated profiles for ZH, JA, KO, EN, FR, ES, DE, IT, PT, RU, TH, VI, YUE, plus generic fallback). Implements a Single-Draft Adversarial 3-Stage Pipeline (Initial Translation -> Independent Falsification Review in fresh context -> Arbitration & Polish) to eliminate confirmation bias and contextual contradictions like literal idiom traps. Supports single-file and directory-wide batch translation. Preserves source lines and inserts exactly one target-language line below each.
metadata:
  version: "3.1.0"
---

# Lyric Translator — Adversarial 3-Stage Pipeline

High-fidelity lyric translation across global languages using dedicated linguistic profiles, strict anti-confirmation-bias role separation, and deterministic `.lrc` timeline merging.

Resolve `<translator-skill>` to the directory containing this `SKILL.md` before running commands.

## Architecture (Single-Draft 3-Stage Pipeline)

Every song runs through **one** initial translator, **one** isolated adversarial reviewer, and **one** arbiter (never duplicate initial drafts against the same file):

```text
[Original LRC]
      ↓
[Step 0: lrc_strip.py] -> <song.lrc>.tmp.txt
      ↓
[Stage 1: Initial Translator (roles/translator.md)] -> Draft .tmp.txt + Handover Memo
      ↓
[Stage 2: Adversarial Reviewer (roles/reviewer.md)] ⚠️ Clean Isolated Context -> Issue Directives
      ↓
[Stage 3: Arbiter (roles/arbiter.md)] -> Final .tmp.txt (+ blocks-plan.json if requested by caller)
      ↓
[Step 4: lrc_merge.py] -> Final Bilingual LRC [OK] (standalone mode only; workflow callers run extract_bilingual.py first)
```

- **Shared rules & red lines**: `reference/common.md` (format lock, metadata immunity, filler passthrough, no plot injection).
- **Language profiles**: `reference/source/{source}.md`, `reference/target/{target}.md` (line length cap & cadence rules; normalize regional tags like `zh-CN` -> `zh.md`, `en-US` -> `en.md`, fallback to `generic.md`), and `reference/pair-exceptions.md`.
- **Role protocols**: `roles/translator.md`, `roles/reviewer.md`, `roles/arbiter.md`.

## Translation Mode

Default to **Reading mode** unless the user says "翻唱", "cover version", "singable translation", "翻配", or explicitly asks for rhyme/rhythm matching.

| Mode | Priority | When to Use |
| :-- | :-- | :-- |
| **Reading** (default) | Semantic integrity > naturalness > singability | Bilingual subtitles, lyric booklets, foreign song comprehension |
| **Cover/Singing** | Singability + rhythm + rhyme > literalness | Creating a performable version in the target language |

## Standalone vs. Workflow Handoff

- **Standalone mode** (user only asks to translate `.lrc` / `.txt` files): Stage 3 Arbiter writes finalized `.tmp.txt`, runs `lrc_merge.py`, and verifies `[OK]`. Do not generate `blocks-plan.json`.
- **Workflow handoff mode** (invoked from `sakurauta-lyrics-workflow` or another pipeline providing `<workdir>/lyric-index.txt`):
  - Stage 1 Translator proposes stanza groupings in its Handover Memo using `l_001`..`l_NNN` IDs from `<workdir>/lyric-index.txt` (does not write `blocks-plan.json`).
  - Stage 3 Arbiter is the **sole author** of `<workdir>/blocks-plan.json` and **STOPS before running `lrc_merge.py`** so the orchestrator can extract `bilingual-lyrics.json` from `.tmp.txt` before merging.

## Multi-File Batch Orchestration

- **Per-song isolation**: Keep each song in its own isolated child contexts; never mix multiple songs into one prompt.
- **Slot-aware concurrency**: Calculate active song pipelines from the runtime's available subagent slots (typically 1–2 concurrent songs in a 4-slot environment; prioritize finishing one song at a time when slots are limited). Never exceed available slots.
- **No-Read Verification**: Once `lrc_merge.py` exits 0 with `[OK]`, timeline alignment and occurrence-ordered pairing are verified; do not re-read the merged `.lrc`.

## Commands

```powershell
# Strip timestamps to create <input.lrc>.tmp.txt:
python -X utf8 "<translator-skill>/scripts/lrc_strip.py" "<input.lrc>" ["<output.tmp.txt>"]
python -X utf8 "<translator-skill>/scripts/lrc_strip.py" "<input1.lrc>" "<input2.lrc>" ...

# Merge translations back into .lrc (occurrence-ordered for repeated lines) & verify [OK]:
python -X utf8 "<translator-skill>/scripts/lrc_merge.py" "<original.lrc>" ["<translated.tmp.txt>"]
python -X utf8 "<translator-skill>/scripts/lrc_merge.py" "<original1.lrc>" "<original2.lrc>" ...
```
