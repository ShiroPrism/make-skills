---
name: lyrics-translator
description: High-fidelity lyric translation across global languages (dedicated profiles for ZH, JA, KO, EN, FR, ES, DE, IT, PT, RU, TH, VI, YUE, plus generic fallback). Implements an Adversarial 3-Stage Pipeline (Initial Translation → Independent Falsification Review in fresh context → Arbitration & Polish) to eliminate confirmation bias and contextual contradictions like literal idiom traps. Supports single-file and directory-wide sliding-window batch translation. Preserves source lines and inserts exactly one target-language line below each.
metadata:
  version: "2.0.0"
---

# Lyric Translator — Adversarial 3-Stage Pipeline

High-fidelity lyric translation across global languages with dedicated linguistic profiles, strict anti-confirmation bias architecture, and deterministic timeline validation.

---

## Quality-First Philosophy

Translating song lyrics differs fundamentally from standard prose: lyrics are cohesive artistic units defined by metaphor, persona, subtext, and rhythmic cadence. Single-agent self-review suffers from severe confirmation bias (e.g., mechanically translating cynical rhetorical questions like 「もういいかい？」 as children's hide-and-seek "藏好了吗？").

To guarantee maximum quality, this skill enforces a **Three-Stage Adversarial Pipeline (三阶段对冲流水线)** for every song:

```
[Original LRC]
      ↓
[Step 0: lrc_strip.py] → .tmp.txt
      ↓
[Stage 1: Initial Translator (roles/translator.md)]
      ↓ (Handover: Draft .tmp.txt + Song Persona Memo)
[Stage 2: Adversarial Reviewer (roles/reviewer.md)] ⚠️ Clean Isolated Context
      ↓ (Issue Directives: Mandatory Critical Fixes & Rhythm Suggestions)
[Stage 3: Arbiter & Finalizer (roles/arbiter.md)]
      ↓ (Adoption Arbitration + Target Cadence Polish)
[Step 4: lrc_merge.py] → Final Bilingual LRC [OK]
```

---

## Translation Mode

Default to **reading mode** unless the user says "翻唱", "cover version", "singable translation", "翻配", or explicitly requests rhyme/rhythm matching.

| Mode | Priority | When to Use |
| :-- | :-- | :-- |
| **Reading** (default) | Semantic integrity > naturalness > singability | Bilingual subtitles, lyric booklets, foreign song comprehension |
| **Cover/Singing** | Singability + rhythm + rhyme > literalness | Creating a performable version in the target language |

---

## Pipeline Execution Details

### Stage 1: Initial Translation (`roles/translator.md`)

Dispatched to translate the raw lyrics stripped by `lrc_strip.py`:

1. **Pre-read & Persona**: Reads the full song to establish the 1–2 sentence Song Persona (speaker, listener, emotional arc, register).
2. **Language Reference Loading**:
   - `reference/common.md`: Absolute red lines, semantic integrity guards, special line rules.
   - `reference/source/{source}.md`: Source-specific grammar signals (e.g., Japanese `て`-form chains, omitted subjects).
   - `reference/target/{target}.md`: Target breath units (4–16 characters for Chinese), register rules.
   - `reference/pair-exceptions.md`: False-friend kanji/cognates.
3. **Dual-Track Output**:
   - **Track 1 (Line-level LRC text)**: Writes the line-by-line translation directly into `.tmp.txt`, adhering strictly to audio sync and line-matching constraints without inverting cross-line word order.
   - **Track 2 (Stanza-level Semantic Chunking & Meaning Plan — Mandatory)**: Writes `<workdir>/blocks-plan.json` to record natural stanza boundaries and coherent literary translations for each block, ensuring dependent enjambments remain unified and downstream sidecars have fluent semantic units.
4. **Handover**: Outputs the Song Persona memo, handover plan, and flags potential ambiguities for the Reviewer. Do not dump or print full translated lyrics in chat messages (the disk file is authoritative).

### Stage 2: Adversarial Quality Review (`roles/reviewer.md`)

Dispatched as a **completely fresh subagent (clean context window)** with zero memory of the translator's thought process:

1. **Operating Mandate**: Operates under the **Adversarial Falsification Protocol (证伪协议)** — hunting aggressively for errors rather than validating the draft.
2. **Core Audit Targets**:
   - **Dictionary First-Sense Traps (首选字面义陷阱)**: Catches idioms or polysemous phrases translated literally that contradict song context (e.g., 「もういいかい？」 as "藏好了吗" vs. cynical "够了吗").
   - **Contextual Contradictions (语境冲突与因果断裂)**: Catches lines creating emotional or logical breaks with lines $N-2 \dots N+2$.
   - **Persona & Pronoun Consistency**: Ensures voice stability and eliminates hallucinated subjects.
   - **Red Line Adherence**: Checks character limits and ensures zero plot injection.
   - **Stanza Boundary Integrity (乐段分界与跨行检查)**: Audits `<workdir>/blocks-plan.json` to ensure mid-sentence enjambments are never cut across blocks (e.g. keeping `May I call you my` and `d-r-e-a-m` together), and confirms each stanza meaning is faithful and complete.
3. **Output**: Structured Issue Directives categorized into `Critical Defects (Mandatory Fixes)` and `Stylistic Polish`.

### Stage 3: Arbitration, Polish & Final Integration (`roles/arbiter.md`)

Finalizes the translation and guarantees deterministic output:

1. **Arbitration**: Mandatorily adopts all confirmed critical defect fixes; arbitrates stylistic suggestions against the Song Persona.
2. **Cadence Polish**: Enforces natural target breath groups (4–16 characters for Chinese) and eliminates translationese (`的`-chains, Europeanized passives).
3. **Physical Write**: Commits revised lines back to `.tmp.txt` in a single write pass rather than multi-turn line edits, and writes the finalized, audited `<workdir>/blocks-plan.json` to disk.
4. **Deterministic Gate**: Runs `python scripts/lrc_merge.py <original.lrc> <translated.tmp.txt>` and verifies console outputs `[OK]`.
   - **No-Read Verification Principle**: Once `lrc_merge.py` exits 0 with `[OK]`, timeline integrity, line-count parity, and metadata immunity are 100% mathematically proven. Never call file-reading tools on merged `.lrc` files.

---

## Multi-File Orchestration (Sliding-Window Pool)

When translating an entire directory, folder, or multiple files, the parent agent acts as a **Sliding-Window Concurrency Pool Coordinator**:

1. **Per-Song Isolation Rule**: Every song is an independent unit. Never mix multiple songs into a single agent's context window. This prevents cross-song style contamination and reviewer attention dilution.
2. **Concurrency Cap**: Maintain a sliding window of **3–5 concurrent song pipelines**.
3. **Queue Progression**:
   - Discover all candidate lyrics files (`*.lrc`, `*.txt`, `*.md`), excluding temporary working files.
   - Dispatch up to 3–5 songs into their respective 3-Stage Pipelines.
   - As each song completes Stage 3 and passes `lrc_merge.py`, immediately pop the next queued song into the active pool.
4. **Final Summary**: Once all queued songs complete, aggregate results into a final markdown delivery table showing each file, persona, lines translated, key corrections adopted, and `[OK]` merge status.

---

## Commands

```powershell
# Strip timestamps to create same-directory .tmp.txt working files:
python <skill-root>/scripts/lrc_strip.py <input.lrc> [<output.tmp.txt>]
python <skill-root>/scripts/lrc_strip.py <input1.lrc> <input2.lrc> ...

# Merge translations back into .lrc & deterministically verify:
python <skill-root>/scripts/lrc_merge.py <original.lrc> [<translated.tmp.txt>]
python <skill-root>/scripts/lrc_merge.py <original1.lrc> <original2.lrc> ...
```
