# Portions adapted from PurffleShorts (MIT), © 2025 Purffle, commit 514fd25: purffle_shorts/timing.py
# (`tokenize`, `norm`, `estimate_timings`, `anchored_timings`, `transfer_timings`, `caption_chunks`).
# Changes: English-only tokenizer, words as [text, start, end] lists (the project format), no speaker field.
"""Word timing for narration takes and the caption chunks built from them. Pure functions."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from difflib import SequenceMatcher

SENTENCE_MARKS, CLAUSE_MARKS = ".!?", ",;:"


@dataclass
class Word:
    text: str
    start: float
    end: float


def normalize_text(text: str) -> str:
    """The canonical form of a narration line: NFC, single spaces, trimmed (shared with the frontend)."""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", text or "")).strip()


def text_sha256(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def tokenize(text: str) -> list[str]:
    return [t for t in normalize_text(text).split(" ") if t]


def norm(token: str) -> str:
    return re.sub(r"[^\w]", "", token.lower(), flags=re.UNICODE)


def _weight(token: str) -> float:
    """How long a token takes to say relative to the others: its length, plus a pause after punctuation."""
    w = len(norm(token)) + 2.0
    if token[-1:] in SENTENCE_MARKS:
        w += 4.0
    elif token[-1:] in CLAUSE_MARKS:
        w += 2.0
    return w


def estimate_timings(tokens: list[str], duration: float, lead: float = 0.05, tail: float = 0.15) -> list[Word]:
    """Spread tokens over ``duration`` by length, with extra time after punctuation."""
    if not tokens:
        return []
    weights = [_weight(t) for t in tokens]
    span = max(0.1, duration - lead - tail)
    scale = span / sum(weights)
    out, t0 = [], lead
    for tok, w in zip(tokens, weights):
        d = w * scale
        pause = 0.0
        if tok[-1:] in SENTENCE_MARKS:
            pause = min(4.0 * scale, d * 0.4)
        elif tok[-1:] in CLAUSE_MARKS:
            pause = min(2.0 * scale, d * 0.3)
        out.append(Word(tok, round(t0, 3), round(t0 + d - pause, 3)))
        t0 += d
    return out


def _anchor(tokens: list[str], weights: list[float], lo: int, hi: int, t0: float, t1: float,
            silences: list[tuple[float, float]], marks: str) -> list[tuple[int, float, float]]:
    cuts: list[tuple[int, float, float]] = []
    seg_tok, seg_t = lo, t0
    for i in range(lo, hi - 1):
        if tokens[i][-1:] not in marks:
            continue
        rest = sum(weights[seg_tok:hi])
        pred = seg_t + (t1 - seg_t) * sum(weights[seg_tok:i + 1]) / rest
        window = 0.35 * (pred - seg_t) + 0.2
        near = [(a, b) for a, b in silences if seg_t < (a + b) / 2 < t1 and abs((a + b) / 2 - pred) <= window]
        if near:
            a, b = min(near, key=lambda c: abs((c[0] + c[1]) / 2 - pred) - 0.5 * (c[1] - c[0]))
            cuts.append((i, a, b))
            seg_tok, seg_t = i + 1, b
    return cuts


def anchored_timings(tokens: list[str], duration: float,
                     silences: list[tuple[float, float]]) -> tuple[list[Word], int]:
    """Word times for audio without word timestamps (a recording): sentence and clause ends are pinned to the real
    pauses in the audio (FFmpeg silencedetect); only the words between two pauses are estimated."""
    if not tokens:
        return [], 0
    silences = sorted(silences)
    lead = silences[0][1] if silences and silences[0][0] <= 0.05 else 0.05
    end = silences[-1][0] if silences and silences[-1][1] >= duration - 0.05 else max(lead + 0.1, duration - 0.15)
    inner = [(a, b) for a, b in silences if a > lead + 0.02 and b < end - 0.02]
    weights = [_weight(t) for t in tokens]
    cuts = _anchor(tokens, weights, 0, len(tokens), lead, end, inner, SENTENCE_MARKS)
    bounds = [(-1, lead, lead)] + cuts + [(len(tokens) - 1, end, end)]
    finer: list[tuple[int, float, float]] = []
    for (i0, _, b0), (i1, a1, _) in zip(bounds, bounds[1:]):
        finer += _anchor(tokens, weights, i0 + 1, i1 + 1, b0, a1, inner, CLAUSE_MARKS)
    cuts = sorted(cuts + finer)
    bounds = [(-1, lead, lead)] + cuts + [(len(tokens) - 1, end, end)]
    words: list[Word] = []
    for (i0, _, b0), (i1, a1, _) in zip(bounds, bounds[1:]):
        part = tokens[i0 + 1:i1 + 1]
        if not part:
            continue
        bare = part[:-1] + [part[-1].rstrip(SENTENCE_MARKS + CLAUSE_MARKS) or part[-1]]
        est = estimate_timings(bare, max(0.05, a1 - b0), lead=0.0, tail=0.0)
        words += [Word(tok, round(b0 + w.start, 3), round(b0 + w.end, 3)) for tok, w in zip(part, est)]
        words[-1].end = round(a1, 3)
    return words, len(cuts)


def transfer_timings(tokens: list[str], timed: list[Word], duration: float) -> list[Word]:
    """Give every script token a time from an engine's (possibly different) word list; unmatched tokens are
    interpolated between their matched neighbours, so captions keep the script's exact wording."""
    if not tokens:
        return []
    if not timed:
        return estimate_timings(tokens, duration)
    a = [norm(t) for t in tokens]
    b = [norm(w.text) for w in timed]
    starts: list[float | None] = [None] * len(tokens)
    ends: list[float | None] = [None] * len(tokens)
    for block in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks():
        for k in range(block.size):
            w = timed[block.b + k]
            starts[block.a + k], ends[block.a + k] = w.start, w.end
    n = len(tokens)
    i = 0
    while i < n:
        if starts[i] is not None:
            i += 1
            continue
        j = i
        while j < n and starts[j] is None:
            j += 1
        left = ends[i - 1] if i > 0 and ends[i - 1] is not None else 0.0
        right = starts[j] if j < n and starts[j] is not None else max(left, duration - 0.1)
        right = max(right, left + 0.05 * (j - i))
        sub = estimate_timings(tokens[i:j], right - left, lead=0.0, tail=0.0)
        for k, w in enumerate(sub):
            starts[i + k], ends[i + k] = left + w.start, left + w.end
        i = j
    out = []
    prev_start = 0.0
    for tok, s, e in zip(tokens, starts, ends):
        s = max(float(s), prev_start)
        e = max(float(e), s + 0.04)
        out.append(Word(tok, round(s, 3), round(e, 3)))
        prev_start = s
    return out


@dataclass
class Chunk:
    words: list[Word]
    start: float
    end: float


def caption_chunks(words: list[Word], max_words: int = 3, max_chars: int = 20, total: float | None = None) -> list[Chunk]:
    """Group words into short on-screen captions; break at sentence ends, long pauses and length limits."""
    chunks: list[Chunk] = []
    cur: list[Word] = []

    def flush():
        if cur:
            chunks.append(Chunk(list(cur), cur[0].start, cur[-1].end))
            cur.clear()

    for w in words:
        if cur:
            gap = w.start - cur[-1].end
            chars = sum(len(x.text) + 1 for x in cur) + len(w.text)
            if len(cur) >= max_words or chars > max_chars or gap > 0.45:
                flush()
        cur.append(w)
        if w.text[-1:] in ".!?;:" or (w.text[-1:] == "," and len(cur) >= 2):
            flush()
    flush()
    for k in range(len(chunks) - 1):
        nxt = chunks[k + 1].start
        chunks[k].end = nxt if nxt - chunks[k].end < 0.6 else chunks[k].end + 0.25
    if chunks:
        end = chunks[-1].end + 0.4
        chunks[-1].end = min(end, total) if total else end
    return chunks


def to_lists(words: list[Word]) -> list[list]:
    return [[w.text, w.start, w.end] for w in words]


def from_lists(raw: list[list]) -> list[Word]:
    return [Word(str(t), float(s), float(e)) for t, s, e in raw]
