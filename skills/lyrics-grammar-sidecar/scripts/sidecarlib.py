#!/usr/bin/env python3
"""Shared implementation for the Schema v3 timestamp-free lyrics grammar sidecar workflow.

The module intentionally uses only the Python standard library. It owns lyric
header/credit filtering, pure-content identities (contentHash, 1-based lineId,
text fingerprint), bilingual-lyrics.json extraction/freezing, the closed JSON
Schema subset validator, and atomic JSON writes.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SIDECAR_SCHEMA_ID = "sakurauta.lyrics-grammar-analysis"
BILINGUAL_SCHEMA_ID = "sakurauta.bilingual-lyrics"
MANIFEST_SCHEMA_ID = "sakurauta.lyrics-grammar-translation-manifest"
ISOLATION_SCHEMA_ID = "sakurauta.lyrics-grammar-isolation-proof"
SEMANTIC_AUDIT_SCHEMA_ID = "sakurauta.lyrics-grammar-semantic-audit"
REPETITION_CANDIDATE_SCHEMA_ID = "sakurauta.lyrics-grammar-repetition-candidates"

SCHEMA_VERSION = 3
BILINGUAL_VERSION = 1
CONTENT_PROJECTION_VERSION = "sakurauta-lrc-content-projection-v3"
LINE_ID_VERSION = "sakurauta-lyric-line-id-v3"
FINGERPRINT_VERSION = "sakurauta-lyric-text-fingerprint-v1"
MANIFEST_VERSION = 2
AUDIT_VERSION = 1
REPETITION_CANDIDATE_VERSION = 2
ISOLATION_VERSION = 3
MIN_REPETITION_CODE_POINTS = 8

ISOLATION_METHODS = {"native-subagent", "codex-exec", "documented-harness"}
ISOLATION_CONTEXT = "non-forked-transcript"
ISOLATION_STAGES = {"grammar-analysis", "semantic-audit"}
LEARNER_LANGUAGE_EXTENSION = "learnerLanguage"
CJK_LEARNER_LANGUAGES = {"zh", "ja", "ko", "yue"}

HASH_PATTERN = re.compile(r"\Asha256:[0-9a-f]{64}\Z")
ID_PATTERN = re.compile(r"\A[a-z][a-z0-9_-]{2,63}\Z")
LRC_SUFFIX = ".lrc"
LRC_LINE_RE = re.compile(r"^\[(\d{2}):(\d{2})(?:\.(\d{1,3}))?\]\s*(.*)$")
LRC_METADATA_TAG_RE = re.compile(r"^\[(?:ti|ar|al|by|offset|yt|youtube):", re.IGNORECASE)
TITLE_LINE_MAX_TIME_MS = 2500
TITLE_LINE_SEPARATOR_RE = re.compile(r"^(.+?)(?:\s+-\s+|\s*[－–—]\s*)(.+)$")

CREDIT_LINE_PATTERNS = (
    re.compile(
        r"^\s*(?:词|詞|作词|作詞|作曲|曲|编曲|編曲|編词|編詞|混音|录音|錄音|"
        r"制作人|製作人|歌|唄|演唱|歌手)\s*[:：]"
    ),
    re.compile(
        r"^\s*(?:Lyrics?|Music|Arrangement|Arrange|Composed|Composer|Produced|"
        r"Producer|Singer|Vocal|Vo\.?)\s*(?:by\s*)?[:：]",
        re.IGNORECASE,
    ),
    re.compile(
        r"^\s*(?:Lyrics?|Music|Arrangement|Composed|Produced)\s+by\s+\S",
        re.IGNORECASE,
    ),
)

FILLER_RE = re.compile(
    r"^(?:[♪♫…\s\.,!~?'\"\(\)（）\-\—\[\]/]+|(?:\b(?:la|na|da|ta|oh|ah|ha|ba|pa|wo|ye|uh|wu|hu|hey|yeah|ooh|wow|scat|du|di|bi|pi|yo)\b[\s♪♫…\.,!~?'\"\(\)（）\-\—]*)+)+$",
    re.IGNORECASE,
)

HTML_TAG_RE = re.compile(r"</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]*)?/?>")
HTML_DECL_RE = re.compile(r"<![A-Za-z]|<\?", re.IGNORECASE)
HTML_COMMENT_RE = re.compile(r"<!--")
HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#[xX][0-9A-Fa-f]+|[A-Za-z][A-Za-z0-9]+);")
FORBIDDEN_TRANSLATION_KEY_RE = re.compile(r"translat", re.IGNORECASE)
ABSOLUTE_PATH_RE = re.compile(
    r"^(?:[A-Za-z]:[\\/]|\\\\|/(?:[^/\s]+/)+|file://)",
    re.IGNORECASE,
)
WINDOWS_ABSOLUTE_PATH_RE = re.compile(r"[A-Za-z]:[\\/]")
FILE_URI_RE = re.compile(r"file://", re.IGNORECASE)
REMOTE_PATH_RE = re.compile(r"^(?:https?|ftp|s3|gs|ssh|file):(?://|[\\/])", re.IGNORECASE)


class SidecarError(Exception):
    """A fatal contract error with a stable machine-readable code."""

    def __init__(self, code: str, message: str, path: str = "$") -> None:
        super().__init__(message)
        self.code = code
        self.path = path
        self.message = message

    def as_issue(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class Issue:
    code: str
    path: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code, "path": self.path, "message": self.message}


class _DuplicateJsonKey(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


class _NonFiniteJsonNumber(ValueError):
    def __init__(self, value: str) -> None:
        super().__init__(value)
        self.value = value


def _reject_duplicate_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateJsonKey(key)
        result[key] = value
    return result


def _parse_finite_json_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed):
        raise _NonFiniteJsonNumber(value)
    return parsed


def _reject_json_constant(value: str) -> None:
    raise _NonFiniteJsonNumber(value)


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(char) <= 0xDFFF for char in value)


def json_value_issues(value: Any, path: str = "$") -> list[Issue]:
    """Return issues for Python values that cannot be represented as strict JSON."""

    issues: list[Issue] = []
    if isinstance(value, str):
        if _contains_surrogate(value):
            issues.append(
                Issue(
                    "invalid_unicode",
                    path,
                    "Unpaired UTF-16 surrogate code points are not valid UTF-8 text.",
                )
            )
    elif isinstance(value, float) and not math.isfinite(value):
        issues.append(Issue("invalid_number", path, "JSON numbers must be finite."))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            issues.extend(json_value_issues(item, f"{path}[{index}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                issues.append(
                    Issue("invalid_json_object", path, "JSON object keys must be strings.")
                )
                continue
            key_path = f"{path}.{key}"
            if _contains_surrogate(key):
                issues.append(
                    Issue(
                        "invalid_unicode",
                        key_path,
                        "JSON object keys must not contain unpaired surrogate code points.",
                    )
                )
            issues.extend(json_value_issues(item, key_path))
    return issues


def parse_json_bytes(data: bytes, label: str = "JSON") -> Any:
    """Decode strict UTF-8 JSON without duplicate keys or non-finite numbers."""

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise SidecarError("invalid_utf8", f"File is not valid UTF-8: {label}") from exc
    try:
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_json_pairs,
            parse_float=_parse_finite_json_float,
            parse_constant=_reject_json_constant,
        )
    except _DuplicateJsonKey as exc:
        raise SidecarError(
            "invalid_json",
            f"Duplicate JSON object key in {label}: {exc.key}",
            "$",
        ) from exc
    except _NonFiniteJsonNumber as exc:
        raise SidecarError(
            "invalid_json",
            f"Non-finite JSON number in {label}: {exc.value}",
            "$",
        ) from exc
    except json.JSONDecodeError as exc:
        raise SidecarError(
            "invalid_json",
            f"Invalid JSON in {label}: line {exc.lineno}, column {exc.colno}",
            "$",
        ) from exc
    except (RecursionError, ValueError) as exc:
        raise SidecarError("invalid_json", f"Invalid JSON in {label}: {exc}", "$") from exc

    issues = json_value_issues(value)
    if issues:
        issue = issues[0]
        raise SidecarError("invalid_json", issue.message, issue.path)
    return value


@dataclass(frozen=True)
class LrcRow:
    line_number: int
    timestamps: tuple[int, ...]
    text: str
    raw: str


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def pretty_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    )


def configure_utf8_stdio() -> None:
    sys.dont_write_bytecode = True
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    if path.is_symlink():
        raise SidecarError(
            "unsupported_source",
            f"Symlinked files are not supported: {path}",
        )
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def assert_distinct_paths(*paths: tuple[str, Path | None]) -> None:
    """Reject aliases between readable artifacts and write destinations."""

    seen: dict[str, str] = {}
    for label, path in paths:
        if path is None:
            continue
        resolved = path.expanduser().resolve()
        key = os.path.normcase(str(resolved))
        if key in seen:
            raise SidecarError(
                "artifact_path_collision",
                f"{label} must not alias {seen[key]}.",
                "$",
            )
        seen[key] = label


def ensure_inside_workdir(path: Path, directory: Path, label: str) -> Path:
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SidecarError(
            "artifact_symlink",
            f"{label} must not be a symlink.",
            "$",
        )
    resolved = expanded.resolve()
    root = directory.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise SidecarError(
            "artifact_outside_workdir",
            f"{label} must live inside the grammar work directory.",
            "$",
        ) from exc
    return resolved


def read_json(path: Path) -> Any:
    if path.is_symlink():
        raise SidecarError(
            "unsupported_source",
            f"Symlinked JSON inputs are not supported: {path}",
        )
    try:
        data = path.read_bytes()
    except FileNotFoundError as exc:
        raise SidecarError("file_not_found", f"File not found: {path}") from exc
    except OSError as exc:
        raise SidecarError("file_read_failed", f"Could not read JSON file: {path}") from exc
    return parse_json_bytes(data, path.name)


def ensure_local_lrc(path: Path) -> Path:
    raw = str(path)
    if REMOTE_PATH_RE.match(raw) or raw.startswith(("\\\\", "//")):
        raise SidecarError(
            "unsupported_source",
            "Remote and network-share inputs are not supported; use a local .lrc file.",
        )
    expanded = path.expanduser()
    if expanded.is_symlink():
        raise SidecarError(
            "unsupported_source",
            "Symlinked LRC inputs are not supported.",
        )
    resolved = expanded.resolve()
    if resolved.suffix.lower() != LRC_SUFFIX:
        raise SidecarError(
            "unsupported_source",
            "Expected a local .lrc file.",
        )
    if not resolved.is_file():
        raise SidecarError("file_not_found", f"LRC file not found: {resolved}")
    return resolved


def _timestamp_ms(minutes: str, seconds: str, fraction: str | None) -> int:
    millis = int((fraction or "0").ljust(3, "0")[:3])
    return (int(minutes) * 60 + int(seconds)) * 1000 + millis


def is_credit_line(text: str) -> bool:
    trimmed = text.strip()
    return bool(trimmed) and any(
        pattern.search(trimmed) for pattern in CREDIT_LINE_PATTERNS
    )


def _is_vocal_filler(text: str) -> bool:
    clean = text.strip()
    if not clean:
        return True
    if FILLER_RE.match(clean):
        return True
    if re.match(r"^[あアいイうウえエおオラらルるー\s\.,!~?'\"\(\)（）]+$", clean):
        return True
    if re.match(r"^[啦啊哦呜耶哈\s\.,!~?'\"\(\)（）]+$", clean):
        return True
    return False


def _normalize_title_line_part(value: str) -> str:
    nfkc = unicodedata.normalize("NFKC", value).lower()
    return re.sub(r"\s+", " ", nfkc).strip()


def _split_title_line(value: str) -> tuple[str, str] | None:
    match = TITLE_LINE_SEPARATOR_RE.match(value.strip())
    if not match:
        return None
    left = _normalize_title_line_part(match.group(1))
    right = _normalize_title_line_part(match.group(2))
    return (left, right) if (left and right) else None


def _song_title_line_references(song_id: str) -> list[str]:
    basename = re.split(r"[\\/]", song_id.strip())[-1] if song_id.strip() else ""
    if basename.lower().endswith(LRC_SUFFIX):
        basename = basename[:-4]
    parts = _split_title_line(basename) or (_normalize_title_line_part(basename), "")
    return [part for part in parts if len(part) >= 2]


def _is_title_artist_header_line(
    time_ms: int,
    text: str,
    references: Sequence[str],
) -> bool:
    if time_ms > TITLE_LINE_MAX_TIME_MS or not references:
        return False
    parts = _split_title_line(text)
    if not parts:
        return False
    return any(ref in part for ref in references for part in parts)


def parse_lrc_rows(path: Path) -> list[LrcRow]:
    """Return timestamped, non-empty, non-credit LRC rows in physical file order."""

    lrc_path = ensure_local_lrc(path)
    try:
        text = lrc_path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError as exc:
        raise SidecarError("invalid_utf8", f"LRC file is not valid UTF-8: {lrc_path}") from exc

    rows: list[LrcRow] = []
    for line_number, raw in enumerate(text.splitlines(), start=1):
        if "\x00" in raw:
            raise SidecarError(
                "invalid_lrc",
                f"NUL character in LRC line {line_number}.",
            )
        match = LRC_LINE_RE.match(raw)
        if match is None:
            continue
        minutes, seconds, fraction, lyric_text = match.groups()
        if not lyric_text.strip() or is_credit_line(lyric_text):
            continue
        rows.append(
            LrcRow(
                line_number=line_number,
                timestamps=(_timestamp_ms(minutes, seconds, fraction),),
                text=lyric_text,
                raw=raw,
            )
        )
    return rows


def filter_title_artist_rows(
    rows: Sequence[LrcRow],
    title_hint: str,
) -> tuple[list[LrcRow], set[str]]:
    """Exclude <=2.5s Title - Artist header rows when real lyric rows follow."""

    references = _song_title_line_references(title_hint)
    candidates = [
        _is_title_artist_header_line(row.timestamps[0], row.text, references)
        for row in rows
    ]
    can_exclude = any(candidates) and any(
        not is_title and row.text.strip()
        for row, is_title in zip(rows, candidates)
    )
    if not can_exclude:
        return list(rows), set()
    kept: list[LrcRow] = []
    excluded_texts: set[str] = set()
    for row, is_title in zip(rows, candidates):
        if is_title:
            excluded_texts.add(row.text.strip())
        else:
            kept.append(row)
    return kept, excluded_texts


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def grammar_line_fingerprint(text: str) -> str:
    return "sha256:" + _sha256_hex(f"{FINGERPRINT_VERSION}\n{_nfc(text)}")


def grammar_line_id(source_order: int) -> str:
    if isinstance(source_order, bool) or not isinstance(source_order, int) or source_order < 0:
        raise SidecarError("invalid_source_order", "sourceOrder must be a non-negative integer.")
    return f"l_{source_order + 1:03d}"


def compute_content_hash(texts: Sequence[str]) -> str:
    payload = "\n".join(
        [
            CONTENT_PROJECTION_VERSION,
            str(len(texts)),
            *(_nfc(text) for text in texts),
        ]
    )
    return "sha256:" + _sha256_hex(payload)


def _build_bilingual_document(
    pairs: Sequence[tuple[str, str | None]],
    *,
    source_languages: Sequence[str] | None = None,
    learner_language: str | None = None,
) -> dict[str, Any]:
    if not pairs:
        raise SidecarError("empty_source", "No lyric lines remain after metadata and header filtering.")
    lines: list[dict[str, Any]] = []
    texts: list[str] = []
    for source_order, (text, translation) in enumerate(pairs):
        clean_translation = translation.strip() if isinstance(translation, str) and translation.strip() else None
        lines.append(
            {
                "lineId": grammar_line_id(source_order),
                "sourceOrder": source_order,
                "text": text,
                "fingerprint": grammar_line_fingerprint(text),
                "translation": clean_translation,
            }
        )
        texts.append(text)
    doc: dict[str, Any] = {
        "schema": BILINGUAL_SCHEMA_ID,
        "schemaVersion": BILINGUAL_VERSION,
        "lineCount": len(lines),
        "contentHash": compute_content_hash(texts),
        "lines": lines,
    }
    if source_languages:
        doc["sourceLanguages"] = sorted(set(source_languages))
    if learner_language:
        doc["learnerLanguage"] = learner_language
    return doc


def extract_source_index_from_lrc(
    lrc_path: Path,
    *,
    title_hint: str | None = None,
) -> list[dict[str, Any]]:
    """Extract canonical filtered lyric lines (l_001..l_NNN) from a source LRC without timestamps."""
    lrc_resolved = ensure_local_lrc(lrc_path)
    raw_rows = parse_lrc_rows(lrc_resolved)
    seen_times: set[int] = set()
    primary_rows: list[LrcRow] = []
    for row in raw_rows:
        t = row.timestamps[0]
        if t in seen_times:
            continue
        seen_times.add(t)
        primary_rows.append(row)

    source_rows, _ = filter_title_artist_rows(
        primary_rows,
        title_hint or lrc_resolved.stem,
    )
    if not source_rows:
        raise SidecarError("empty_source", "No source lyric lines were found in LRC.")

    return [
        {
            "lineId": grammar_line_id(order),
            "sourceOrder": order,
            "text": row.text,
        }
        for order, row in enumerate(source_rows)
    ]


def extract_bilingual_from_lrc_and_tmp(
    lrc_path: Path,
    tmp_txt_path: Path,
    *,
    title_hint: str | None = None,
    source_languages: Sequence[str] | None = None,
    learner_language: str | None = None,
) -> dict[str, Any]:
    """Extract timestamp-free bilingual lines from source LRC + translated .tmp.txt.

    Timestamps are used in memory solely for same-timestamp deduplication
    and <=2.5s title-line exclusion, then discarded completely.
    """

    lrc_resolved = ensure_local_lrc(lrc_path)
    tmp_resolved = tmp_txt_path.expanduser()
    if tmp_resolved.is_symlink():
        raise SidecarError("unsupported_source", f"Symlinked input is not supported: {tmp_resolved}")
    tmp_resolved = tmp_resolved.resolve()
    if not tmp_resolved.is_file():
        raise SidecarError("file_not_found", f"Translated text file not found: {tmp_resolved}")

    raw_rows = parse_lrc_rows(lrc_resolved)
    # Deduplicate same-timestamp rows so only the primary source row enters if the LRC was already bilingual.
    seen_times: set[int] = set()
    primary_rows: list[LrcRow] = []
    for row in raw_rows:
        t = row.timestamps[0]
        if t in seen_times:
            continue
        seen_times.add(t)
        primary_rows.append(row)

    source_rows, excluded_titles = filter_title_artist_rows(
        primary_rows,
        title_hint or lrc_resolved.stem,
    )
    if not source_rows:
        raise SidecarError("empty_source", "No source lyric lines were found in LRC.")

    try:
        tmp_lines_raw = tmp_resolved.read_text(encoding="utf-8-sig").splitlines()
    except UnicodeDecodeError as exc:
        raise SidecarError("invalid_utf8", f"Translated text file is not valid UTF-8: {tmp_resolved}") from exc

    tmp_tokens = [line.strip() for line in tmp_lines_raw if line.strip()]
    source_texts = [row.text for row in source_rows]
    source_stripped = [text.strip() for text in source_texts]

    pairs: list[tuple[str, str | None]] = []
    cursor = 0
    for index, raw_text in enumerate(source_texts):
        expected_nfc = _nfc(source_stripped[index])
        matched_pos: int | None = None
        for probe in range(cursor, len(tmp_tokens)):
            if _nfc(tmp_tokens[probe]) == expected_nfc:
                matched_pos = probe
                break
        if matched_pos is None:
            raise SidecarError(
                "bilingual_alignment_failed",
                f"Source line {index + 1} ({raw_text!r}) not found in {tmp_resolved.name}.",
            )
        cursor = matched_pos + 1
        next_expected_nfc = (
            _nfc(source_stripped[index + 1]) if index + 1 < len(source_texts) else None
        )

        # Advance cursor past any non-lyric metadata/credit/excluded-title line before reading translation.
        while cursor < len(tmp_tokens):
            candidate = tmp_tokens[cursor]
            if next_expected_nfc is not None and _nfc(candidate) == next_expected_nfc:
                break
            if (
                LRC_METADATA_TAG_RE.match(candidate)
                or is_credit_line(candidate)
                or candidate in excluded_titles
            ):
                cursor += 1
                continue
            break

        translation: str | None = None
        if cursor < len(tmp_tokens):
            candidate = tmp_tokens[cursor]
            if next_expected_nfc is not None and _nfc(candidate) == next_expected_nfc:
                translation = None
            else:
                translation = candidate
                cursor += 1
        pairs.append((raw_text, translation))

    return _build_bilingual_document(
        pairs,
        source_languages=source_languages,
        learner_language=learner_language,
    )


def extract_bilingual_from_bilingual_lrc(
    bilingual_lrc_path: Path,
    *,
    title_hint: str | None = None,
    source_languages: Sequence[str] | None = None,
    learner_language: str | None = None,
) -> dict[str, Any]:
    """Thin adapter: strip timestamps from an existing bilingual .lrc into bilingual-lyrics.json."""

    lrc_resolved = ensure_local_lrc(bilingual_lrc_path)
    raw_rows = parse_lrc_rows(lrc_resolved)
    filtered_rows, _excluded = filter_title_artist_rows(
        raw_rows,
        title_hint or lrc_resolved.stem,
    )
    if not filtered_rows:
        raise SidecarError("empty_source", "No lyric lines were found in bilingual LRC.")

    pairs: list[tuple[str, str | None]] = []
    index_by_time: dict[int, int] = {}
    for row in filtered_rows:
        t = row.timestamps[0]
        if t not in index_by_time:
            index_by_time[t] = len(pairs)
            pairs.append((row.text, None))
        else:
            target_idx = index_by_time[t]
            existing_text, existing_trans = pairs[target_idx]
            if existing_trans is None:
                pairs[target_idx] = (existing_text, row.text)
            else:
                raise SidecarError(
                    "duplicate_translation_row",
                    f"Multiple translation rows found at timestamp line {row.line_number}.",
                )

    return _build_bilingual_document(
        pairs,
        source_languages=source_languages,
        learner_language=learner_language,
    )


def _schema_path(name: str) -> Path:
    return Path(__file__).resolve().parents[1] / "schema" / "v3" / name


def validate_bilingual_lyrics(document: Any) -> list[Issue]:
    if not isinstance(document, dict):
        return [Issue("invalid_bilingual_lyrics", "$", "Bilingual lyrics document must be a JSON object.")]
    schema = read_json(_schema_path("bilingual-lyrics.schema.json"))
    issues = validate_schema_instance(document, schema)
    if issues:
        return issues

    lines = document.get("lines", [])
    if document.get("lineCount") != len(lines):
        issues.append(
            Issue(
                "line_count_mismatch",
                "$.lineCount",
                "lineCount must equal len(lines).",
            )
        )
        return issues

    texts: list[str] = []
    for index, line in enumerate(lines):
        path = f"$.lines[{index}]"
        if line.get("sourceOrder") != index:
            issues.append(
                Issue("non_canonical_line_order", path + ".sourceOrder", "sourceOrder must equal array index.")
            )
        if line.get("lineId") != grammar_line_id(index):
            issues.append(
                Issue("invalid_line_id", path + ".lineId", f"Expected {grammar_line_id(index)}.")
            )
        text = line.get("text", "")
        if line.get("fingerprint") != grammar_line_fingerprint(text):
            issues.append(
                Issue("invalid_line_fingerprint", path + ".fingerprint", "Line fingerprint is not canonical.")
            )
        translation = line.get("translation")
        if isinstance(translation, str) and not translation.strip():
            issues.append(
                Issue("blank_translation", path + ".translation", "Translation must be null or non-blank.")
            )
        texts.append(text)

    if not issues and document.get("contentHash") != compute_content_hash(texts):
        issues.append(
            Issue(
                "invalid_content_hash",
                "$.contentHash",
                "contentHash does not match canonical NFC line texts.",
            )
        )
    return issues


def load_bilingual_lyrics(path: Path) -> dict[str, Any]:
    doc = read_json(path)
    issues = validate_bilingual_lyrics(doc)
    if issues:
        raise SidecarError(issues[0].code, issues[0].message, issues[0].path)
    return doc


def _has_acceptable_translations(
    bilingual: dict[str, Any],
    *,
    allow_untranslated: bool = False,
) -> list[Issue]:
    if allow_untranslated:
        return []
    lines = bilingual.get("lines", [])
    translated_count = sum(1 for line in lines if isinstance(line.get("translation"), str) and line["translation"].strip())
    if translated_count > 0:
        return []
    non_filler = [line["text"] for line in lines if not _is_vocal_filler(line["text"])]
    if not non_filler:
        return []
    return [
        Issue(
            "missing_translation",
            "$.lines",
            "Bilingual lyrics contain no translated lines (pass --allow-untranslated if intentionally untranslated).",
        )
    ]


def write_accepted_bilingual(
    bilingual_path: Path,
    workdir: Path,
    *,
    allow_untranslated: bool = False,
    replace: bool = False,
) -> tuple[Path, dict[str, Any], list[Issue]]:
    """Freeze a validated bilingual-lyrics.json into bilingual-lyrics.frozen.json + manifest."""

    workdir = workdir.expanduser().resolve()
    if not workdir.is_dir():
        raise SidecarError("invalid_workdir", f"Work directory not found: {workdir}")

    bilingual = load_bilingual_lyrics(bilingual_path)
    issues = _has_acceptable_translations(bilingual, allow_untranslated=allow_untranslated)
    frozen_path = ensure_inside_workdir(workdir / "bilingual-lyrics.frozen.json", workdir, "frozen bilingual lyrics")
    manifest_path = ensure_inside_workdir(workdir / "translation-manifest.json", workdir, "translation manifest")
    if issues:
        return frozen_path, {"ok": False, "contentHash": bilingual["contentHash"]}, issues

    if (frozen_path.exists() or manifest_path.exists()) and not replace:
        raise SidecarError(
            "translation_already_frozen",
            "Refusing to replace an existing frozen translation; use --replace or a fresh workdir.",
        )

    write_json_atomic(frozen_path, bilingual, replace=replace)
    bilingual_sha = sha256_file(frozen_path)
    manifest = {
        "schema": MANIFEST_SCHEMA_ID,
        "manifestVersion": MANIFEST_VERSION,
        "lineCount": bilingual["lineCount"],
        "contentHash": bilingual["contentHash"],
        "bilingualSha256": bilingual_sha,
    }
    write_json_atomic(manifest_path, manifest, replace=replace)
    return frozen_path, manifest, []


def validate_manifest(manifest: Any) -> list[Issue]:
    if not isinstance(manifest, dict):
        return [Issue("invalid_manifest", "$", "Translation manifest must be an object.")]
    required = {
        "schema",
        "manifestVersion",
        "lineCount",
        "contentHash",
        "bilingualSha256",
    }
    issues: list[Issue] = []
    if set(manifest) != required:
        issues.append(
            Issue(
                "invalid_manifest",
                "$",
                "Manifest fields do not match translation manifest v2.",
            )
        )
    if manifest.get("schema") != MANIFEST_SCHEMA_ID:
        issues.append(Issue("invalid_manifest", "$.schema", "Unexpected manifest schema."))
    if manifest.get("manifestVersion") != MANIFEST_VERSION:
        issues.append(
            Issue("unsupported_manifest_version", "$.manifestVersion", "Expected manifestVersion 2.")
        )
    line_count = manifest.get("lineCount")
    if not isinstance(line_count, int) or isinstance(line_count, bool) or line_count < 1:
        issues.append(Issue("invalid_manifest", "$.lineCount", "Expected a positive integer."))
    for key in ("contentHash", "bilingualSha256"):
        val = manifest.get(key)
        if not isinstance(val, str) or HASH_PATTERN.fullmatch(val) is None:
            issues.append(Issue("invalid_manifest", f"$.{key}", f"Invalid {key}."))
    return issues


def verify_frozen_bilingual(
    frozen_path: Path,
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, list[Issue]]:
    issues = validate_manifest(manifest)
    if issues:
        return (
            {
                "ok": False,
                "contentHash": manifest.get("contentHash") if isinstance(manifest, dict) else None,
                "lineCount": 0,
                "translatedLines": 0,
            },
            None,
            issues,
        )
    if not frozen_path.is_file():
        return (
            {"ok": False, "contentHash": manifest["contentHash"], "lineCount": 0, "translatedLines": 0},
            None,
            [Issue("file_not_found", "$", f"Frozen bilingual file not found: {frozen_path}")],
        )

    actual_sha = sha256_file(frozen_path)
    if manifest.get("bilingualSha256") != actual_sha:
        return (
            {"ok": False, "contentHash": manifest["contentHash"], "lineCount": 0, "translatedLines": 0},
            None,
            [
                Issue(
                    "translation_changed_after_freeze",
                    "$.bilingualSha256",
                    "The frozen bilingual lyrics changed after the accepted translation was frozen.",
                )
            ],
        )

    bilingual = read_json(frozen_path)
    bilingual_issues = validate_bilingual_lyrics(bilingual)
    if bilingual_issues:
        return (
            {"ok": False, "contentHash": manifest["contentHash"], "lineCount": 0, "translatedLines": 0},
            None,
            bilingual_issues,
        )
    if bilingual["contentHash"] != manifest["contentHash"]:
        issues.append(
            Issue(
                "stale_content_hash",
                "$.contentHash",
                "Manifest contentHash does not match frozen bilingual lyrics.",
            )
        )
    if bilingual["lineCount"] != manifest["lineCount"]:
        issues.append(
            Issue(
                "line_count_mismatch",
                "$.lineCount",
                "Manifest lineCount does not match frozen bilingual lyrics.",
            )
        )
    translated_lines = sum(
        1 for line in bilingual["lines"] if isinstance(line.get("translation"), str) and line["translation"].strip()
    )
    report = {
        "ok": not issues,
        "contentHash": bilingual["contentHash"],
        "lineCount": bilingual["lineCount"],
        "translatedLines": translated_lines,
        "bilingualSha256": actual_sha,
    }
    return report, bilingual, issues


SUPPORTED_SCHEMA_KEYWORDS = {
    "$schema",
    "$id",
    "$defs",
    "$ref",
    "title",
    "description",
    "type",
    "additionalProperties",
    "required",
    "properties",
    "items",
    "minItems",
    "maxItems",
    "uniqueItems",
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "enum",
    "const",
}


def _walk_schema(schema: Any, path: str = "$schema") -> list[Issue]:
    issues: list[Issue] = []
    if not isinstance(schema, dict):
        return [Issue("invalid_schema", path, "Schema node must be an object.")]
    for key in sorted(set(schema) - SUPPORTED_SCHEMA_KEYWORDS):
        issues.append(
            Issue(
                "unsupported_schema_keyword",
                f"{path}.{key}",
                f"Unsupported schema keyword: {key}",
            )
        )
    if "pattern" in schema:
        try:
            re.compile(schema["pattern"])
        except (re.error, TypeError) as exc:
            issues.append(
                Issue("invalid_schema", f"{path}.pattern", f"Invalid regex pattern: {exc}")
            )
    if "$ref" in schema and len(schema) != 1:
        issues.append(
            Issue(
                "invalid_schema",
                path,
                "$ref nodes may not contain sibling schema keywords.",
            )
        )
    if "$defs" in schema and isinstance(schema["$defs"], dict):
        for name, child in schema["$defs"].items():
            issues.extend(_walk_schema(child, f"{path}.$defs.{name}"))
    if "properties" in schema and isinstance(schema["properties"], dict):
        for name, child in schema["properties"].items():
            issues.extend(_walk_schema(child, f"{path}.properties.{name}"))
    if "items" in schema:
        issues.extend(_walk_schema(schema["items"], f"{path}.items"))
    if isinstance(schema.get("additionalProperties"), dict):
        issues.extend(
            _walk_schema(schema["additionalProperties"], f"{path}.additionalProperties")
        )
    return issues


def _json_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    return "unknown"


def _type_matches(value: Any, expected: str) -> bool:
    actual = _json_type(value)
    if expected == "number":
        return actual in {"integer", "number"}
    return actual == expected


def _json_equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right)
        )
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _resolve_ref(root: dict[str, Any], reference: str) -> tuple[dict[str, Any] | None, str]:
    if not reference.startswith("#/"):
        return None, f"Only local $ref values are supported: {reference}"
    node: Any = root
    for part in reference[2:].split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if not isinstance(node, dict) or part not in node:
            return None, f"Unresolved $ref: {reference}"
        node = node[part]
    if not isinstance(node, dict):
        return None, f"$ref does not resolve to a schema object: {reference}"
    return node, ""


def validate_schema_instance(
    instance: Any,
    schema: dict[str, Any],
    root_schema: dict[str, Any] | None = None,
    path: str = "$",
) -> list[Issue]:
    """Validate the deliberately small, closed schema subset used by v3."""

    if root_schema is None:
        value_issues = json_value_issues(instance, path=path)
        if value_issues:
            return value_issues
    root = root_schema or schema
    issues: list[Issue] = []

    if "$ref" in schema:
        target, error = _resolve_ref(root, schema["$ref"])
        if target is None:
            return [Issue("invalid_schema", path, error)]
        return validate_schema_instance(instance, target, root, path)

    expected_type = schema.get("type")
    if expected_type is not None:
        types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not all(isinstance(item, str) for item in types):
            return [Issue("invalid_schema", path, "Schema type must be a string or array.")]
        if not any(_type_matches(instance, item) for item in types):
            issues.append(
                Issue(
                    "schema_type",
                    path,
                    f"Expected type {types}, got {_json_type(instance)}.",
                )
            )
            return issues
    if (
        "minimum" in schema
        and isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and instance < schema["minimum"]
    ):
        issues.append(
            Issue("schema_minimum", path, f"Value must be at least {schema['minimum']}.")
        )
    if (
        "maximum" in schema
        and isinstance(instance, (int, float))
        and not isinstance(instance, bool)
        and instance > schema["maximum"]
    ):
        issues.append(
            Issue("schema_maximum", path, f"Value must be at most {schema['maximum']}.")
        )
    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            issues.append(
                Issue(
                    "schema_min_length",
                    path,
                    f"Expected at least {schema['minLength']} characters.",
                )
            )
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            issues.append(
                Issue(
                    "schema_max_length",
                    path,
                    f"Expected at most {schema['maxLength']} characters.",
                )
            )
        if "pattern" in schema and re.search(schema["pattern"], instance) is None:
            issues.append(Issue("schema_pattern", path, "String does not match pattern."))

    if "const" in schema and not _json_equal(instance, schema["const"]):
        issues.append(Issue("schema_const", path, f"Expected constant {schema['const']!r}."))
    if "enum" in schema and not any(_json_equal(instance, item) for item in schema["enum"]):
        issues.append(Issue("schema_enum", path, "Value is not in the allowed enum."))

    if isinstance(instance, dict):
        required = schema.get("required", [])
        if isinstance(required, list):
            for key in required:
                if isinstance(key, str) and key not in instance:
                    issues.append(Issue("schema_required", f"{path}.{key}", "Required field."))
        properties = schema.get("properties", {})
        if not isinstance(properties, dict):
            issues.append(Issue("invalid_schema", path, "properties must be an object."))
            properties = {}
        for key, value in instance.items():
            if key in properties and isinstance(properties[key], dict):
                issues.extend(
                    validate_schema_instance(
                        value, properties[key], root, f"{path}.{key}"
                    )
                )
                continue
            additional = schema.get("additionalProperties", True)
            if additional is False:
                issues.append(
                    Issue("schema_additional_property", f"{path}.{key}", "Unknown field.")
                )
            elif isinstance(additional, dict):
                issues.extend(
                    validate_schema_instance(value, additional, root, f"{path}.{key}")
                )

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            issues.append(
                Issue("schema_min_items", path, f"Expected at least {schema['minItems']} items.")
            )
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            issues.append(
                Issue("schema_max_items", path, f"Expected at most {schema['maxItems']} items.")
            )
        if schema.get("uniqueItems") is True:
            seen: list[Any] = []
            for index, item in enumerate(instance):
                if any(_json_equal(item, previous) for previous in seen):
                    issues.append(
                        Issue(
                            "schema_unique_items",
                            f"{path}[{index}]",
                            "Duplicate array item.",
                        )
                    )
                seen.append(item)
        if isinstance(schema.get("items"), dict):
            for index, item in enumerate(instance):
                issues.extend(
                    validate_schema_instance(
                        item, schema["items"], root, f"{path}[{index}]"
                    )
                )

    return issues


def _write_bytes_atomic(path: Path, data: bytes) -> None:
    if path.is_symlink():
        raise SidecarError(
            "artifact_symlink",
            f"Refusing to write through a symlink: {path}",
            "$",
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def write_json_atomic(path: Path, value: Any, replace: bool = False) -> bool:
    if path.is_symlink():
        raise SidecarError(
            "artifact_symlink",
            f"Refusing to write through a symlink: {path}",
            "$",
        )
    data = pretty_json(value).encode("utf-8")
    if path.exists():
        existing = path.read_bytes()
        if existing == data:
            return False
        if not replace:
            raise SidecarError(
                "output_exists",
                f"Refusing to overwrite a different file without --replace: {path}",
            )
    _write_bytes_atomic(path, data)
    return True
