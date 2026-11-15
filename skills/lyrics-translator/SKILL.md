---
name: lyrics-translator
description: Translate song lyrics across all global languages (with dedicated profiles for Chinese/ZH, Japanese/JA, Korean/KO, English/EN, French/FR, Spanish/ES, German/DE, Italian/IT, Portuguese/PT, Russian/RU, Thai/TH, Vietnamese/VI, Cantonese/YUE, and extensible generic fallback for all others) in .lrc, .txt, or .md files. Supports single-file and directory-wide batch translation. Automatically activates batch mode when translating a directory, multiple files, or when scanning discovers multiple lyrics files. Preserves the source line and inserts exactly one target-language line below it.
version: 1.1.0
---

# Lyric Translator — Bilingual Interleaved Lyrics

Translate across global languages with dedicated profiles and an extensible architecture. Keep instructions in English; do not translate the core prompt or duplicate rules by direction.

## Translation Mode

Detect which mode the user wants. Default to **reading mode** unless the user says "翻唱", "cover version", "singable translation", "翻配", or explicitly requests rhyme/rhythm matching.

| Mode | Priority | When to use |
| :-- | :-- | :-- |
| **Reading** (default) | Semantic integrity > naturalness > singability | Bilingual subtitles, lyric booklets, understanding foreign songs |
| **Cover/Singing** | Singability + rhythm + rhyme > literalness | Creating a performable version in the target language |

In **reading mode**, follow the standard workflow below. In **cover mode**, additionally load the selected target profile's rhythm rules as hard constraints and actively pursue natural rhyme patterns (near-rhyme is acceptable; forced rhyme that distorts meaning is not).

## Workflow

1. Detect file mode. For `.lrc`, run this skill's `scripts/lrc_strip.py` to produce a same-directory `.tmp.txt` working file. For `.txt` and `.md`, work on the original file.
2. Detect **primary** source and target languages. Use the user's explicit direction first, then filename hints, then lyrics inspection:
   - **Kana** (平假名/片假名) → `ja`
   - **Hangul** (한글) → `ko`
   - **Cyrillic** (Русский) → `ru`
   - **Thai script** (ภาษาไทย) → `th`
   - **Vietnamese diacritics** (đ, ơ, ư, ả, ã, ạ, ắ...) → `vi`
   - **CJK ideographs without kana/Hangul**:
     - Contains vernacular Cantonese particles (嘅, 咗, 仲, 唔, 咁, 哋, 乜, 點) or tagged in title/album → `yue`
     - Otherwise → `zh`
   - **Latin script**:
     - German markers (ä, ö, ü, ß) → `de`
     - French markers (é, è, ê, ç, œ, à, ù) → `fr`
     - Spanish markers (ñ, ¿, ¡, á, é, í, ó, ú) → `es`
     - Portuguese markers (ã, õ, ç, ê) → `pt`
     - Italian vocabulary and characteristic vocalic endings → `it`
     - English vocabulary (the, you, I, my, we, and) → `en`
     - Other languages → identify ISO 639-1 code (e.g. `ar`, `hi`, `el`, `nl`, `sv`, `tr`, etc.).
   - Ask only if the target or source language remains ambiguous.
   - **Multi-language blocks**: Some songs contain blocks of lyrics in different languages (e.g., several lines in Japanese, then several lines in English, then back to Japanese). Detection of secondary source languages happens during Step 1 of `reference/common.md`.
3. Handle existing translations:
   - **No existing translations**: proceed normally.
   - **Existing translations in the same target language**: ask the user whether to keep, overwrite, or skip each section. If the user says "重新翻译" or "redo", overwrite all.
   - **Existing translations in a different language**: treat them as non-source lines — pass through unchanged. Insert the new target-language translation below the source line only.
4. Before editing, load reference files dynamically:
   - `reference/common.md`
   - **Source profile**: `reference/source/{source}.md` if it exists; otherwise fall back to `reference/source/generic.md`.
   - **Target profile**: `reference/target/{target}.md` if it exists; otherwise fall back to `reference/target/generic.md`.
   - **Pair exceptions**: `reference/pair-exceptions.md` if an entry matching `{source}→{target}` or their language families exists.
   - If Step 1 of common.md detected secondary source languages, load each `reference/source/{secondary}.md` (or `generic.md`) at that point.
5. Follow the numbered workflow in `reference/common.md`. Read the complete working file before writing; make one editing pass; run this skill's `scripts/lrc_merge.py` only after quality checks pass.

## Extensible Language Support (We are the World)

This skill utilizes an open, modular language architecture:

- **Dedicated Profiles**: High-frequency music languages have hand-crafted profiles in `reference/source/` and `reference/target/`:
  - East Asian: `zh` (Mandarin), `ja` (Japanese), `ko` (Korean), `yue` (Cantonese)
  - Southeast Asian: `th` (Thai), `vi` (Vietnamese)
  - European / Romance: `en` (English), `fr` (French), `es` (Spanish), `it` (Italian), `pt` (Portuguese)
  - Germanic & Slavic: `de` (German), `ru` (Russian)
- **Universal Fallback**: Any other language in the world immediately functions through `reference/source/generic.md` and `reference/target/generic.md`.
- **Zero-Code Expansion**: To add specialized deep-tuning for any new language (e.g. Arabic `ar`, Swedish `sv`, Hindi `hi`), simply create `reference/source/{lang}.md` and `reference/target/{lang}.md` following the existing format. The skill will discover and apply them automatically without changing any code or scripts.

## Rule Selection

Use source references to understand cross-line grammar, ellipsis, and source-specific meaning. Use target references to write natural, concise, singable output. Consult pair exceptions only for genuine bilateral pitfalls; they supplement rather than replace the other two files.

Never load obsolete direction files or invent pair-specific rules that are not required by the lyric at hand.

## Batch Mode (Directory & Multi-File Orchestration)

Automatically activate batch mode whenever the user requests translating an entire directory or folder (e.g., "翻译某个文件夹下的所有文件", "batch translate folder"), or when scanning a path reveals multiple lyrics files.

### 1. File Discovery & Concurrency Partitioning

1. Scan the target directory for all candidate lyrics files (`*.lrc`, `*.txt`, `*.md`), automatically excluding temporary files (`*.tmp.txt`, `.grammar-work`, etc.).
2. Partition the discovered files into batches of up to 5 files each.
3. Maintain up to 5 concurrent subagents (using `invoke_subagent`), with each subagent assigned one batch.
4. Advance the batch process fully autonomously without requiring step-by-step user confirmations.

### 2. Core Execution Constraints for Subagents

Every subagent dispatched for a batch must strictly follow these three rules:

1. **Mandatory Full Skill & Reference Execution**: Each subagent translating assigned files must first completely read and strictly execute `lyrics-translator`'s `SKILL.md` and the entire set of reference rules (`reference/common.md` semantic chunking, `reference/source/{source}.md`, `reference/target/{target}.md`, and `reference/pair-exceptions.md`). Cutting corners, omitting reference rules, or performing direct line-by-line literal translation is strictly forbidden.
2. **Efficient Batching & No-Read Verification Principle (免读验证原则)**:
   - Call `python <skill-root>/scripts/lrc_strip.py <file1> <file2>...` to strip timestamps in batch and create same-directory `.tmp.txt` working files.
   - Translate lyrics in plain text directly within each `.tmp.txt` file without timestamp distractions.
   - Call `python <skill-root>/scripts/lrc_merge.py <file1> <file2>...` to merge translations back into the original `.lrc` files and run deterministic timeline validation.
   - **No-Read Verification**: `lrc_merge.py` performs rigorous deterministic bilingual line-count, timestamp, and metadata verification. As long as the console outputs `[OK]`, the merge is 100% verified. **Subagents and parent agents are strictly forbidden from calling file-reading tools (`read_file`, etc.) to re-read merged `.lrc` files**, saving massive context tokens and execution time.
3. **Role Isolation & Autonomous Progression**:
   - Subagents focus exclusively on their assigned lyric translations without reading global configurations, unrelated files, or large state files.
   - Proceed fully autonomously through the batch without pausing for per-file user confirmation.

### 3. Subagent Dispatch Prompt Template

When dispatching subagents for batch translation, pass this standardized prompt:

```text
Read and follow <skill-root>\SKILL.md.
You are assigned to translate the following lyrics files into <target language>:
- <file1>
- <file2>
...

Strict Execution Requirements:
1. Mandatory Full Skill Execution: You must first completely read and strictly follow SKILL.md and its referenced rules (reference/common.md for semantic chunking, reference/source/<source>.md, reference/target/<target>.md, and reference/pair-exceptions.md). Never cut corners or translate line-by-line literally.
2. Efficient Batching & No-Read Verification:
   - Run: python <skill-root>\scripts\lrc_strip.py <file1> <file2> ...
   - Translate pure lyrics in plain text within each .tmp.txt file.
   - Run: python <skill-root>\scripts\lrc_merge.py <file1> <file2> ...
   - No-Read Verification Principle: Once lrc_merge.py outputs [OK], the output is 100% verified. DO NOT call read_file or any inspection tools to re-read merged .lrc files.
3. Role Isolation: Focus exclusively on your assigned batch of files. Do not inspect global state or unrelated project files. Report final status upon completion.
```

### 4. Batch Result Aggregation

After all subagents report completion:

1. Aggregate the results into a markdown summary table showing each file name, source language, line count, and merge verification status (`[OK]`).
2. Offer the standard post-translation revision options to the user.

## Post-Translation

After completing the translation and delivering the file, offer the user a follow-up option:

> Translation complete. To revise specific lines, reply with the line numbers or quote the lines you'd like changed. To polish the entire translation, reply "继续润色" or "refine".

For **line-level revision**: re-read the surrounding 3–5 line context, apply the same source/target/pair rules, and replace only the specified lines. For **full polish**: re-run Steps 5–6 of common.md (Refine + Quality Check) on the existing output.

## Commands

```powershell
# Strip timestamps (single file, batch files, or stdout):
python <skill-root>/scripts/lrc_strip.py <input.lrc> [<output.tmp.txt>]
python <skill-root>/scripts/lrc_strip.py <input1.lrc> <input2.lrc> ...
python <skill-root>/scripts/lrc_strip.py --print <input.lrc>

# Merge translations back & verify deterministically (single or batch):
python <skill-root>/scripts/lrc_merge.py <original.lrc> [<translated.tmp.txt>]
python <skill-root>/scripts/lrc_merge.py <original1.lrc> <original2.lrc> ...
```
