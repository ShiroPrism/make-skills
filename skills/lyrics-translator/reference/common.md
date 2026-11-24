# Lyric Translation — Shared Rules

Applies to all global translation directions across world languages (dedicated profiles for ZH, JA, KO, EN, FR, ES, DE, IT, PT, RU, TH, VI, YUE, plus generic fallback for all others). Use with the selected source and target references, plus any applicable pair exception.

---

## Quick Reference: 8 Core Rules

When invoked frequently, apply these 8 rules first:

1. **Source lines only**: Do not touch target-language lines, metadata lines, blank lines, or pure sound-effect lines (`♪`/`♫`).
2. **Read entire file first**: The first tool call must be a single `read_file` of the full lyrics file. Assess the song's subject, emotional tone, and narrative POV (first person / third person / duet / multi-voice) before writing anything. **Never interleave reads and writes.**  
   For duets/multi-voice: build a speaker map before translating — identical pronoun forms used by different voices must not be translated the same way.
3. **Pre-read context**: Before translating each line, review 3–5 lines before and after to catch long-sentence splits, chained grammar, and code-mixed passages.
4. **Core before modifier**: Translate the action/conclusion/emotional core first, then decide on modifiers and register.
5. **Singability over literalism**: Translations must be clear, natural, and singable. Single-line length must stay within the cap defined in the target-language file; split at natural breath points rather than cramming onto one line.
6. **Translation priority order** — When rules conflict, apply in this order:
   1. **Semantic integrity** (highest) — block-level meaning must be preserved
   2. **Timeline alignment** — one output line per source line
   3. **Single-line readability** (lowest) — desirable but subordinate to #1 and #2

   → Do **not** force a non-closing clause into a complete standalone sentence to satisfy single-line readability. Front-loading the next line's conclusion is also prohibited. However, **never leave an orphaned modifier particle at the end of a line** (such as a bare trailing `的` in Chinese from a Japanese pre-nominal clause). Reframe the modifier line into a natural scene or state clause without trailing `的`, and resume the head noun on the next line with a demonstrative or continuation.

7. **Consistent key terms & rhythmic weight**: Use the same translation for choruses, hooks, core imagery, and the song title throughout the entire file, and keep identical key terms across Track 1 (`.tmp.txt`) and Track 2 (`blocks-plan.json`). When a multi-syllable foreign loanword or core hook (5+ syllables/morae, such as `メタモルフォーゼ`) carries strong musical weight, prefer an idiomatic expression grounded in its etymology and song motif (e.g., `破茧蜕变`) rather than collapsing it into a clipped two-character gloss (`蜕变`)—provided the line stays within the target length cap. Reuse identical wording for repeated lines.
8. **Final check before output**: Confirm no target-language lines were modified, no metadata was touched, no third line was stacked onto a source line, no plot points were added, and all line lengths are within cap.

---

## Absolute Constraints (Red Lines)

| Constraint | Rule |
| :-- | :-- |
| **Format Lock** | The agent writes **plain text only** — never insert timestamp tokens into translation lines. LRC structure and timestamps are managed entirely by `lrc_merge.py`. (Plain Mode: same rule — no timestamps exist.) |
| **Metadata Immunity** | Lines beginning with `[ti:` `[ar:` `[al:` `[by:` `[offset:` and embedded production credits (`词：`/`曲：`/`編曲：`/`作詞：`/`Lyrics:`/`Music:` etc.) must never be translated or modified. |
| **No Re-translation** | Do not re-translate or modify lines already in the target language. |
| **One Translation Per Source Line** | Each source line gets exactly one same-timestamp translation line inserted below it. If a translation already exists, overwrite/correct it — never stack a third line. |
| **Filler Line Passthrough** | Pure vocalization filler lines (`Oh oh oh`/`La la la`/`오오오`/`啦啦啦`/`あーあー` etc.) pass through unchanged — no translation inserted. |
| **No Plot Injection** | Paraphrase may expand information already in the source. It must never add plot points, characters, motivations, or identities not present in the original. |
| **Completeness** | Every repeated lyric line must be translated. Do not skip or merge lines. |
| **Line Length Cap** | Single translated lines must not exceed the cap specified in the target-language file. Split at natural breath points when over the limit. |
| **Skip Empty/SFX Lines** | Blank timestamp lines (empty or whitespace content) and pure sound-effect lines (`[01:23.45]♪`) pass through unchanged — no translation inserted. |

---

## Pipeline Architecture: The 3-Stage Quality Protocol

Translation quality is guaranteed through strict separation of responsibilities across three dedicated roles. The same agent context must NEVER perform both translation and final quality review.

```
Stage 1: Initial Translation (roles/translator.md)
  ↓ (Handover: Draft .tmp.txt + Song Persona Memo)
Stage 2: Adversarial Quality Review (roles/reviewer.md — Clean Isolated Context)
  ↓ (Issue Directives: Mandatory Fixes & Contextual Contradiction Flags)
Stage 3: Arbiter & Finalizer (roles/arbiter.md)
  ↓ (Arbitration + Rhythm Polish)
Physical Integration: lrc_merge.py [OK]
```

### Stage 1 Standards — Initial Translation (Translator)

- Complete full survey before drafting; define the 1–2 sentence Song Persona.
- Construct semantic blocks (Semantic Chunking) — never translate chained modifiers or incomplete predicates in isolation.
- Lock key phrases, proverbs, and katakana loanwords contextually before drafting.
- Output line-by-line draft directly to `.tmp.txt`.

### Stage 2 Standards — Adversarial Review (Reviewer)

- Runs in a completely fresh, isolated context (Zero-Memory Principle).
- Executes the Adversarial Falsification Protocol:
  - **Dictionary First-Sense Traps**: flags phrases translated only by literal dictionary definition #1 that clash with song context (e.g., 「もういいかい？」 as "藏好了吗" vs. cynical "够了吗").
  - **Contextual Contradictions**: flags lines creating sudden, unmotivated emotional or causal breaks with surrounding lines.
  - **Narrative Persona & Pronoun Drift**: verifies speaker identity and consistency.
  - **Red Line Compliance**: verifies no plot injection, length within cap, and metadata preservation.
- Outputs structured Issue Directives.

### Stage 3 Standards — Arbiter & Finalizer (Arbiter)

- **Mandatory Adoption**: All confirmed critical defects (contextual contradictions, dictionary traps, mistranslations) must be corrected.
- **Persona Arbitration**: Stylistic polish suggestions are accepted or rejected based on alignment with the Song Persona.
- **Rhythm Polish**: Checks breath groups, cadence (4–16 Chinese characters), and removes translationese.
- **Deterministic Gate**: Writes final `.tmp.txt` and executes `lrc_merge.py` for timestamp and metadata integrity.

---

## Paraphrase vs. Over-Interpretation

Paraphrase is natural expansion of **information already in the source**. Over-interpretation **adds new plot, identity, scene, or motivation** not present in the original.

| Judgment | Example |
| :-- | :-- |
| ✓ **Acceptable paraphrase** — extends implied emotion naturally | `want to disappear` → `想消失不见` |
| ✗ **Over-interpretation** — adds specifics not in the source | `想消失在失恋的痛苦里` ("heartbreak" is invented) |
| ✓ **Acceptable** — reorders into natural target-language expression | Idiom or colloquial naturalization |
| ✗ **Prohibited** — expands poetic ellipsis into prose annotation | `running in the rain` → `不顾一切地向前冲，忘记所有伤痛` (invented motivation) |
| ✗ **Prohibited** — invents a second half to force a parallel couplet | すいも甘いもわからないの → `尝不出酸甜 摸不清好坏` ("好坏/good vs bad" is invented; the source idiom is only about sour and sweet) |
| ✗ **Prohibited** — adds a head noun the source does not contain | きっと君の前では迷子 → `迷路的小孩` ("小孩" invented; 迷子 needs no noun) |

Use `reference/source/{source}.md`, `reference/target/{target}.md`, and applicable entries in `reference/pair-exceptions.md` for concrete language guidance.

---

## Special Line Handling

| Line Type | Detection Criterion | Action |
| :-: | :-- | :-: |
| Blank timestamp line | `[01:23.45]` with empty or whitespace content | Pass through, no translation |
| Pure SFX / interlude marker | `[01:23.45]♪` or `[01:23.45]♫` | Pass through, no translation |
| LRC metadata tag | Starts with `[ti:` `[ar:` `[al:` `[by:` `[offset:` | Never translate or modify |
| Embedded production credit | Contains `词：` `曲：` `編曲：` `作詞：` `作曲：` `Lyrics:` `Music:` etc. | Never translate or modify |
| Already-target-language line | Entire line is in target language | Pass through, no translation |
| Filler vocalization in another language | Short exclamatory line in a non-primary language with no semantic content (e.g. `Yeah yeah`, `Oh baby`, `Come on`) | Pass through, no translation |
| Secondary-language block | 2+ consecutive lines entirely in a non-primary source language **with semantic content** (see Multi-Source-Language Detection in Step 1) | Translate using that language's source rules |
| Filler vocalization | `오오오` / `あーあー` / `Oh oh oh` / `La la la` / `啦啦啦` etc. | Pass through, no translation |
| Code-mixed line | Source language mixed with other languages **within a single line** | Preserve source line; translate overall meaning using primary source rules |
| Ellipsis pause line | `…` denoting trailing-off or silence | Preserve `…` in translation, or carry the pause feeling into register |

---

## Format Reference

### LRC Mode — what the agent edits (`.tmp.txt` working file)

**Input `.tmp.txt`** (after `lrc_strip.py`):

```
Song Title - Artist
词：Lyricist
Source lyric line one
Source lyric line two
Existing target-language line
♪

```

**Correct output `.tmp.txt`** (after agent translation):

```
Song Title - Artist
词：Lyricist
Source lyric line one
Translated line one
Source lyric line two
Translated line two
Existing target-language line
♪

```

**Final `.lrc`** (after `lrc_merge.py`):

```lrc
[ti:Song Title]
[ar:Artist]
[00:15.19]Source lyric line one
[00:15.19]Translated line one
[00:18.50]Source lyric line two
[00:18.50]Translated line two
[01:22.40]Existing target-language line
[00:20.00]♪
[00:25.00]
```

### Plain Mode — what the agent edits (`.txt` / `.md` directly)

**Input:**

```
Song Title - Artist
词：Lyricist
Source lyric line one
Source lyric line two
♪
```

**Correct output:**

```
Song Title - Artist
词：Lyricist
Source lyric line one
Translated line one
Source lyric line two
Translated line two
♪
```

> `♪` lines, blank lines, already-target-language lines, and metadata lines pass through unchanged — no translation inserted.
