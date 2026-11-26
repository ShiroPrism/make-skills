# Japanese Source Lyrics

## Read Before Translating

- Resolve omitted subjects, objects, and causal links from the whole block.
- Interpret particles, sentence-final particles, auxiliary verbs, passive/causative forms, and register as meaning and tone, not isolated tokens.
- Render katakana loanwords and 擬音語/擬態語 for their intended effect rather than preserving Japanese sounds.

## Semantic-Chunking Signals

Make one semantic block when consecutive lines contain any of these:

- `て`-form, `ながら`, `ように`, `のに`, or other connective forms without final closure.
- A modifier clause whose head noun or predicate appears on the next line.
- A final-particle or ellipsis line whose speaker stance depends on the next line.
- A subject/object omission whose referent appears elsewhere in the passage.

## Common Traps

- Do not invent an English-like explicit subject unless the block resolves it.
- Do not inject plural `"我们"` for Japanese volitional `〜おう / 〜よう` (e.g., `遊ぼう`, `しよう`, `踊ろう`) when the song's narrative perspective is singular `"我"` speaking to `"你"` (`君`); render as a direct intimate invitation (`……吧`) unless context clearly establishes a plural `"we"`.
- Do not read kanji by its Chinese meaning; consult the pair exception for Chinese targets.
- Preserve the speaker’s intimacy, distance, and gender-neutrality unless context establishes otherwise.

## Phrase-Level Resolution Traps

- **Truncated kotowaza**: lyrics often quote half a proverb. Recover the full proverb, then render its contextual intent. 酸いも甘いもわからないの stands on 酸いも甘いも噛み分ける ("to know life's bitter and sweet") — here: too smitten to tell love's flavors. Never translate the fragment character by character, and never invent a matching second half.
- **Poetic subject resolution**: parse what governs what before choosing an imperative or descriptive reading. 心遊ばせ = "let the heart roam/play" (心 is what plays) — not a command to the listener to go play. Wrong: 尽情嬉戏吧. Right: 放任心儿跃动.
- **Katakana loanwords**: render the original foreign word's meaning (ランデブー → a date/tryst; プラトニック → platonic/pure), never the phonetics or the glyph shape.
- **Homophone puns** (e.g. 愛 / 相 both あい): when the pun cannot survive translation, fuse the two senses into one rendering ("gazes meet and become love") rather than silently dropping one.
- **Register in denial patterns**: 〜では…無い combined with どう頑張ったって is flustered colloquial speech ("calm and composed? no way, not me") — keep the spoken tone; do not elevate it into formal written style.
- **Pre-nominal modifier split across lines**: When line 1 ends in a Japanese attributive verb/clause (`〜た`, `〜る`, `〜ている`) whose head noun appears on line 2 (e.g., `憧れていた扉から溢れた / 光を掬ってみた`), do not front-load line 2's noun or main verb into line 1, and do not end line 1 with a dangling Chinese `的` (`从曾憧憬的门扉流溢而出的`). Render line 1 as a clean scene/action clause without trailing `的` (`自憧憬的门扉满溢而出`) and resume the head noun naturally on line 2 (`试着捧起那束光芒`).
