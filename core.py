"""Pure transcript selection logic for AUTOCLIP AI."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

# Small encode margin keeps the verified MP4 safely within the requested range.
MIN_SECONDS = 10.2
MAX_SECONDS = 39.8
STOP = frozenset("a an and are as at be but by for from had has have i in is it its of on or our that the their there these this to was we were what when where who why will with you your yeah okay so well um uh like just really very actually basically".split())
OPENERS = ("here's the", "here is the", "here's why", "here is why", "the reason", "the problem", "the key", "the truth", "what people", "most people", "if you", "when you", "my advice", "the biggest", "one thing", "imagine", "you have to", "you need to", "you don't have to", "i would never")
INSIGHT = ("because", "that means", "which means", "that's why", "the reason", "for example", "instead of", "the mistake", "i learned", "i realized", "you should", "you need to", "you have to", "don't", "never", "always", "the result", "what happens", "look for", "take profits", "set your stops")
DEPENDENT_START = ("and ", "but ", "because ", "so ", "yeah ", "yep ", "right ", "exactly ", "okay ", "well ", "um ", "uh ", "like ", "it ", "it's ", "this ", "that ", "that's ", "those ", "these ", "they ", "he ", "she ", "then ", "else ", "strictly ", "as i said", "you can use those")
WEAK_END = frozenset("and but because so or to of for with in on at a an the if when that which as than is are was were be been do does did can could would should will not has have had um uh really actually maybe probably".split())
PHRASE_STARTS = ("if you", "when you", "you should", "you need to", "you have to", "you don't have to", "i would never", "i learned", "i realized", "the biggest", "the problem", "the reason", "one thing", "my advice", "most people", "what people", "here is the", "here's the")


@dataclass(frozen=True)
class Word:
    start: float
    end: float
    text: str

    def __post_init__(self) -> None:
        if not (math.isfinite(self.start) and math.isfinite(self.end) and 0 <= self.start < self.end):
            raise ValueError("Invalid word timestamp")
        if not self.text.strip():
            raise ValueError("Empty transcript word")


@dataclass(frozen=True)
class Candidate:
    start: float
    end: float
    text: str
    score: float
    reasons: tuple[str, ...]
    words: tuple[Word, ...]


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def tokens(text: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9']+", text.lower()) if len(x) > 2 and x not in STOP}


def similarity(left: str, right: str) -> float:
    a, b = tokens(left), tokens(right)
    return len(a & b) / max(1, len(a | b))


def _score(words: tuple[Word, ...], text: str, end_gap: float) -> tuple[float, tuple[str, ...]]:
    low = text.lower()
    duration = words[-1].end - words[0].start
    word_count = len(words)
    rate = word_count * 60 / duration
    reasons: list[str] = []
    score = 40.0
    if any(low.startswith(x) for x in OPENERS):
        score += 12
        reasons.append("engaging opening")
    elif low.startswith(DEPENDENT_START):
        score -= 15
        reasons.append("depends on earlier context")
    elif re.match(r"^(?:i|you|we) (?:think|believe|found|learned|realized)\b", low):
        score += 4
        reasons.append("personal perspective")
    insight_count = sum(x in low for x in INSIGHT)
    score += min(16, insight_count * 5)
    if insight_count:
        reasons.append("explanation or actionable insight")
    if any(term in low for term in ("but", "however", "instead", "even though", "rather than")):
        score += 5
        reasons.append("useful contrast")
    if any(term in low for term in ("so you", "that's why", "which means", "that means", "the result", "leads to")):
        score += 5
        reasons.append("clear consequence")
    if re.search(r"\b\d+(?:[.,]\d+)?\s*(?:%|percent|dollars?|minutes?|hours?|trades?|times?)\b", low):
        score += 3
        reasons.append("concrete detail")
    if re.search(r"[.!?][\"']?$", text):
        score += 7
        reasons.append("punctuated ending")
    elif end_gap >= 0.8:
        score += 8
        reasons.append("natural speech pause")
    elif end_gap >= 0.45:
        score += 4
        reasons.append("short speech pause")
    else:
        score -= 10
    trailing = re.findall(r"[a-z']+", low)
    if trailing and trailing[-1] in WEAK_END:
        score -= 18
        reasons.append("unfinished ending")
    if rate < 80 or rate > 230:
        score -= 10
        reasons.append("awkward speech pace")
    if word_count < 27:
        score -= 10
    if any(term in low for term in ("can you hear me", "no worries", "thanks for joining", "shout out", "subscribe to", "how are you")):
        score -= 20
        reasons.append("conversation housekeeping")
    if any(term in low for term in ("this discord", "this stream", "our community")):
        score -= 8
        reasons.append("depends on this show")
    if any(term in low for term in ("who me", "can you hear", "i don't even know", "what do you hold")):
        score -= 12
        reasons.append("unfinished conversation")
    if any(term in low for term in ("exactly what you're saying", "like you said", "as you said", "we talked about", "as i mentioned")):
        score -= 12
        reasons.append("depends on another speaker")
    if "that might not make sense" in low[-80:]:
        score -= 15
        reasons.append("undercut ending")
    final_half = low[len(low) // 2:]
    if re.search(r"[.!?]\s+(?:yeah|yep|right)\b", final_half):
        score -= 14
        reasons.append("new thought starts near ending")
    unique_ratio = len(tokens(text)) / max(1, word_count)
    score += min(6, unique_ratio * 12)
    filler = len(re.findall(r"\b(?:um|uh|you know|sort of|kind of)\b", low))
    score -= min(14, filler * 3)
    interjections = len(re.findall(r"\b(?:yeah|yep|right|literally|bro)\b", low))
    if interjections >= 3:
        score -= min(12, interjections * 2)
        reasons.append("conversational filler")
    gaps = [b.start - a.end for a, b in zip(words, words[1:])]
    if gaps and max(gaps) > 2.0:
        score -= 15
        reasons.append("long pause inside clip")
    if duration < 14:
        score -= 6
    elif 20 <= duration <= 34:
        score += 4
    if duration > 37:
        score -= 4
    return round(max(0, min(100, score)), 1), tuple(reasons)


def generate_candidates(words: Iterable[Word]) -> list[Candidate]:
    seq = tuple(words)
    if any(b.start < a.start for a, b in zip(seq, seq[1:])):
        raise ValueError("Transcript words must be ordered")
    if not seq:
        return []
    # Livestream ASR can stop emitting punctuation for long stretches. Pauses
    # remain available from word timestamps and provide useful edit points.
    starts = [0]
    for i in range(1, len(seq)):
        prev, cur = seq[i - 1], seq[i]
        phrase = " ".join(w.text.strip(" .,?!\"'").lower() for w in seq[i:i + 5])
        if (re.search(r"[.!?][\"']?$", prev.text.strip()) or cur.start - prev.end >= 0.45
                or any(phrase.startswith(x) for x in PHRASE_STARTS)):
            starts.append(i)
    result: list[Candidate] = []
    for start_i in starts:
        base = seq[start_i].start
        for end_i in range(start_i, len(seq)):
            duration = seq[end_i].end - base
            if duration > MAX_SECONDS:
                break
            if duration < MIN_SECONDS:
                continue
            final = seq[end_i].text.strip()
            next_gap = seq[end_i + 1].start - seq[end_i].end if end_i + 1 < len(seq) else 9.0
            if not (re.search(r"[.!?][\"']?$", final) or next_gap >= 0.45 or end_i + 1 == len(seq)):
                continue
            window = seq[start_i:end_i + 1]
            text = normalize(" ".join(w.text.strip() for w in window))
            score, reasons = _score(window, text, next_gap)
            result.append(Candidate(base, seq[end_i].end, text, score, reasons, window))
    return result


def select_clips(candidates: Iterable[Candidate], limit: int = 10,
                 extra_score: Callable[[Candidate], float] | None = None) -> list[Candidate]:
    if not 1 <= limit <= 10:
        raise ValueError("limit must be from 1 to 10")
    ranked = []
    for item in candidates:
        if not MIN_SECONDS <= item.end - item.start <= MAX_SECONDS:
            continue
        bonus = 0.0 if extra_score is None else extra_score(item)
        if not math.isfinite(bonus):
            continue
        total = item.score + bonus
        if total < 78:
            continue
        ranked.append((total, item))
    ranked.sort(key=lambda row: (row[0], -(row[1].end - row[1].start)), reverse=True)
    chosen: list[Candidate] = []
    for total, item in ranked:
        if any(min(item.end, c.end) - max(item.start, c.start) > 1.0 for c in chosen):
            continue
        if any(similarity(item.text, c.text) > 0.48 for c in chosen):
            continue
        chosen.append(Candidate(item.start, item.end, item.text,
                                round(min(100, total), 1), item.reasons, item.words))
        if len(chosen) == limit:
            break
    return chosen


def make_title(text: str) -> str:
    sentence = re.split(r"[.!?]", text, maxsplit=1)[0]
    words = re.findall(r"[A-Za-z0-9']+", sentence)
    title = " ".join(words[:8]).strip()
    return title[:65] or "Interview Highlight"


def make_caption(candidate: Candidate) -> str:
    title = make_title(candidate.text).rstrip(" .,?!")
    return f"{title}.\n\n{candidate.text[:220].rstrip()}\n\n#Shorts #Interview #Podcast"
