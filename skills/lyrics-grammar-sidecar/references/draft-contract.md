# Schema v3 Draft & Enrichment Contract

Grammar Child receives only `<workdir>/bilingual-lyrics.frozen.json`, optional `<workdir>/blocks-plan.json`, and this contract, then authors `<workdir>/semantic-draft.json` conforming to Schema v3 (`schema: "sakurauta.lyrics-grammar-analysis"`, `schemaVersion: 3`).

## 1. Input Artifact: `bilingual-lyrics.frozen.json`

Timestamps, untimed metadata tags (`[ti:]`, `[ar:]`, etc.), credit lines (`词：`, `曲：`, `Lyrics:`, etc.), blank lines, and `<= 2.5s` `Title - Artist` header lines are already removed before entering this stage. Every row in `lines` is a real lyric line:

```json
{
  "schema": "sakurauta.bilingual-lyrics",
  "schemaVersion": 1,
  "lineCount": 4,
  "contentHash": "sha256:...",
  "sourceLanguages": ["ja"],
  "learnerLanguage": "zh-CN",
  "lines": [
    {
      "lineId": "l_001",
      "sourceOrder": 0,
      "text": "君がくれた",
      "fingerprint": "sha256:...",
      "translation": "你给我的"
    },
    {
      "lineId": "l_002",
      "sourceOrder": 1,
      "text": "Ah〜",
      "fingerprint": "sha256:...",
      "translation": null
    }
  ]
}
```

- `lineId`: 1-based zero-padded sequential ID (`l_001`, `l_002`, ...; 4+ digits for >999 lines).
- `sourceOrder`: 0-based canonical order (`0 .. lineCount - 1`).
- `translation`: finalized line translation (preserving context-sensitive translations across repeated lines), or `null` for vocal fillers / untranslated lines.

## 2. `blocks-plan.json` Contract

`blocks-plan.json` defines stanza blocks using canonical `l_001`..`l_NNN` line IDs (individual IDs or `"l_001-l_003"` ranges; legacy 1-based integers are also parsed by `scaffold_draft.py` for compatibility):

```json
{
  "blocks": [
    { "lines": ["l_001", "l_002", "l_003"], "meaning": "你给我的那个小小约定，直到如今我都还清楚记得。" },
    { "lines": ["l_004"], "meaning": "那是你曾经交给我的约定。" }
  ]
}
```

- Under `sakurauta-lyrics-workflow`, Stage 3 Arbiter is the sole author of `blocks-plan.json`.
- When running directly on an external bilingual `.lrc` (Path B) without `blocks-plan.json`, Grammar Child creates `<workdir>/blocks-plan.json` from `bilingual-lyrics.frozen.json` before scaffolding.
- Every line `l_001`..`l_NNN` must appear monotonically with zero gaps or duplicates, and every block `meaning` must cover all lines in that block. Never create a `b_meta` block.

## 3. Scaffold -> Enrich -> Resolve -> Repetition Flow

### Step 1: Scaffold & Inspect `DRAFT INDEX`

```powershell
python -X utf8 "<grammar-skill>/scripts/scaffold_draft.py" "<workdir>" --learner-language "<target>"
```

`scaffold_draft.py` writes `<workdir>/semantic-draft.json` and prints the `DRAFT INDEX` in this exact format (block ID + lineId range + per-line Unicode code-point counts):

```text
--- DRAFT INDEX (for enrichment.json) ---
[b_01] l_001..l_003 (3 lines)
  1 | l_001 (5 cp) | 君がくれた
  2 | l_002 (6 cp) | 小さな約束を
  3 | l_003 (8 cp) | 今も覚えている
```

### Step 2: Author Compact `<workdir>/enrichment.json`

Write `<workdir>/enrichment.json` instead of hand-editing offsets in `semantic-draft.json`. Specify `sourceSegments` with `lineId` + exact `text` substring (`start`/`end` are resolved in Unicode code points by `resolve_spans.py`).

**Allowed top-level keys in `enrichment.json`** (any other key raises `invalid_enrichment`):

| Key | Type | Merge Behavior |
| :-- | :-- | :-- |
| `phrases` | `array` | Replaces `draft.phrases`; spans auto-resolved |
| `grammarNotes` | `array` | Replaces `draft.grammarNotes` |
| `relations` | `array` | Replaces `draft.relations` |
| `uncertainties` | `array` | Replaces `draft.uncertainties` |
| `meaningUnits` | `array` (optional) | Replaces `draft.meaningUnits` when splitting a block into multiple parts or adding `semanticOverride`; spans auto-resolved |
| `blocks` | `array` (optional) | Patches matching scaffolded blocks by `blockId`; allowed patch keys are `blockId`, `meaning`, `labels`, `register`, `notes`, `confidence` (`lineIds` are preserved) |
| `excludedRepetitions` | `array` (optional) | Writes `[{"repetitionId": "rep_...", "reason": "..."}]` into `draft.extensions.excludedRepetitions` to exclude spurious substring candidates |

Example `enrichment.json`:

```json
{
  "phrases": [
    {
      "phraseId": "p_promise",
      "kind": "phrase",
      "role": "theme",
      "labels": [{ "namespace": "syntax", "key": "relative_clause" }],
      "explanation": "动词过去式连体修饰名词“約束”。",
      "gloss": "你给我的小小约定",
      "confidence": 0.92,
      "occurrences": [
        {
          "occurrenceId": "po_promise_1",
          "blockId": "b_01",
          "sourceSegments": [
            { "lineId": "l_001", "text": "君がくれた" },
            { "lineId": "l_002", "text": "小さな約束を" }
          ]
        }
      ]
    }
  ],
  "relations": [],
  "grammarNotes": [
    {
      "noteId": "gn_promise_rel",
      "scope": { "blockIds": ["b_01"], "phraseId": "p_promise", "occurrenceIds": ["po_promise_1"] },
      "explanation": "「くれた」表示对方为自己做出的动作并延续到后续记忆。",
      "labels": [{ "namespace": "syntax", "key": "modifier" }],
      "confidence": 0.9
    }
  ],
  "uncertainties": []
}
```

### Step 3: Merge Spans & Discover Repetitions

```powershell
python -X utf8 "<grammar-skill>/scripts/resolve_spans.py" "<workdir>/semantic-draft.json" --merge-enrichment "<workdir>/enrichment.json" --in-place
python -X utf8 "<grammar-skill>/scripts/discover_repetitions.py" "<workdir>/semantic-draft.json" --workdir "<workdir>" --learner-language "<target>" --in-place --replace --check-draft
```

- **Learner language consistency**: Pass the exact same `<target>` tag (e.g., `zh-CN` or `zh`) to `scaffold_draft.py`, `discover_repetitions.py`, and all downstream orchestrator scripts.
- **Repetition discovery & pruning**: `discover_repetitions.py` finds maximal exact NFC repetitions (`>= 8` Unicode code points) across learning blocks, automatically trims mid-ASCII-word cuts and 1-character stray cross-line bleeds, populates `repetitionGroups`, and (with `--check-draft`) runs full Schema v3 draft validation immediately so issues are caught before leaving Grammar Child. If an accidental cross-word substring candidate still appears in `repetition-candidates.json` (for example a coincidence across unrelated words rather than a real repeated lyric hook), exclude it explicitly with a clear reason in `--learner-language`:
  - Either pass `--exclude "<repetitionId>=<reason>"` to `discover_repetitions.py`, or include `"excludedRepetitions": [{"repetitionId": "...", "reason": "..."}]` in `enrichment.json` and re-run `resolve_spans.py` + `discover_repetitions.py`.
  - `prepare.py` verifies `repetitionGroups` equals the discovered candidates minus validated `extensions.excludedRepetitions`.
- **Shared occurrences, partial-overlap blocks & overrides**: For every kept `repetitionGroup`, any `phrase` or `meaningUnit` inside one occurrence must map to the corresponding span in every other block of that group (sharing the canonical meaning/gloss, or attaching a `semanticOverride` with a non-empty `reason`).
  - **Partial-overlap blocks** (e.g., Chorus 1 has an extra leading/trailing line `このまま` that Final Chorus lacks): Because `scaffold_draft.py` initially creates 1:1 `meaningUnits` per block, `discover_repetitions.py --check-draft` (and `prepare.py`) will flag `shared-occurrence-incomplete` unless you split the longer block in `enrichment.json` using `blocks` (`meaning.parts`) and `meaningUnits` — one occurrence covering the exact `repetitionGroup` span across both blocks, and a separate `meaningUnit` covering the non-overlapping remainder:
    ```json
    "blocks": [
      {
        "blockId": "b_04",
        "meaning": {
          "parts": [
            { "meaningUnitOccurrenceId": "muo_b_04_rep" },
            { "meaningUnitOccurrenceId": "muo_b_04_tail" }
          ]
        }
      }
    ]
    ```
  - Multi-part `blocks[].meaning.parts` must cover every line in `block.lineIds` without duplicate boundary punctuation.

## 4. Forbidden Schema v3 Fields & Content Guards

- **Forbidden metadata/timeline fields**: `lrcFile`, `songId`, `lrcProjectionHash`, `timeMs`, `startTimeMs`, `endTimeMs`, `sameTimestampOrdinal`, or `b_meta` blocks fail Schema v3 validation (`additionalProperties: false`).
- **No per-line translation keys**: Keys containing `translat` inside `lines` or `blocks` are rejected in the output sidecar. Compose holistic block meanings through `meaningUnits` + `blocks[].meaning.parts`.
- **No HTML/XML, absolute paths, or wrong learner language**: All prose fields (including `excludedRepetitions[].reason`) must be plain text in `extensions.learnerLanguage`.
