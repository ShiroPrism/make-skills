# Lyric Translation — Shared Rules

Applies to all translation directions. Combine with `reference/source/{source}.md`, `reference/target/{target}.md`, and `reference/pair-exceptions.md`.

## Translation Priority Order

When stylistic goals conflict, resolve them in this strict order:

1. **Semantic integrity** (highest) — preserve block-level meaning and speaker persona.
2. **Timeline alignment** — insert at most one translated line directly below each source line; never invert cross-line clause order across timestamps (do not front-load line 2's main verb onto line 1).
3. **Single-line readability** (lowest) — desirable, but never force an incomplete clause into a standalone sentence at the expense of #1 or #2. Exception: never end a line with an orphaned modifier particle (such as dangling `的` in Chinese); reframe the modifier line as a clean scene/state clause and resume the noun on the next line.

For duets or multi-voice tracks, map speaker voices before translating so identical pronouns spoken by different characters keep distinct registers. Lock recurring hooks, choruses, and multi-syllable title motifs consistently across the entire song (and match multi-syllable hooks with cadence-appropriate expressions rather than over-clipping them).

## Absolute Constraints (Red Lines)

| Constraint | Rule |
| :-- | :-- |
| **Plain Text Only** | Write plain text only in `.tmp.txt` — never insert `[MM:SS.xx]` timestamps. |
| **Metadata Immunity** | Never translate or modify `[ti:]`, `[ar:]`, `[al:]`, `[by:]`, `[offset:]` tags or production credits (`词：`, `曲：`, `編曲：`, `作詞：`, `Lyrics:`, `Music:`, etc.). |
| **No Re-translation** | Do not modify lines already in the target language. |
| **One Translation Per Line** | Insert exactly one translation line directly below each source lyric line; never stack a third line. |
| **Filler & SFX Passthrough** | Blank lines, pure sound-effect markers (`♪`, `♫`), and pure vocal fillers (`Oh oh oh`, `La la la`, `あーあー`, `오오오`, `啦啦啦`, short non-semantic exclamations like `Yeah yeah`) pass through untouched with no translation inserted. |
| **No Plot Injection** | Paraphrase may express implied emotion already in the source, but must never invent plot points, characters, motivations, parallel couplet halves, or head nouns absent from the original. |
| **Completeness** | Translate every repeated lyric line; never skip or merge source lines. |
| **Line Length Cap** | Respect the exact character/length ceiling defined in `reference/target/{target}.md` (for Chinese: 4–16 preferred, 18 hard ceiling). |

## Paraphrase vs. Over-Interpretation

| Judgment | Example |
| :-- | :-- |
| ✓ **Acceptable paraphrase** — extends implied emotion naturally | `want to disappear` → `想消失不见` |
| ✗ **Over-interpretation** — invents backstory absent from source | `想消失在失恋的痛苦里` ("heartbreak" invented) |
| ✗ **Prohibited** — invents a second half to force parallelism | `すいも甘いもわからないの` → `尝不出酸甜 摸不清好坏` ("好坏" invented) |
| ✗ **Prohibited** — invents an absent head noun | `きっと君の前では迷子` → `迷路的小孩` ("小孩" invented) |

## Special Line Handling

| Line Type | Action |
| :-- | :-- |
| Blank line / `♪` / `♫` / metadata tag / production credit / already target language / pure vocal filler | Pass through unchanged (no translation inserted) |
| Secondary-language block (2+ consecutive lines with semantic content) | Translate using that language's source profile |
| Code-mixed single line | Preserve source line; translate overall meaning using primary source rules |
| Ellipsis pause line (`…`) | Preserve `…` or carry the trailing-off cadence into the translation |

## `.tmp.txt` Format Reference

Input `.tmp.txt` (from `lrc_strip.py`):

```text
Song Title - Artist
词：Lyricist
Source lyric line one
Source lyric line two
♪
```

Output `.tmp.txt` (written by Translator / finalized by Arbiter):

```text
Song Title - Artist
词：Lyricist
Source lyric line one
Translated line one
Source lyric line two
Translated line two
♪
```
