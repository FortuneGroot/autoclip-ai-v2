"""Timestamp guidance validates input and chooses nearby, nonoverlapping clips."""
from __future__ import annotations

import unittest

from analysis.revise_job import near_markers, parse_markers
from core import Candidate, Word


def candidate(start: float, end: float, score: float) -> Candidate:
    word = Word(start, end, "Useful complete idea.")
    return Candidate(start, end, word.text, score, (), (word,))


class RefineTest(unittest.TestCase):
    def test_timestamp_boundaries(self) -> None:
        self.assertEqual(parse_markers("12:34\n1:02:15", 4000), [754.0, 3735.0])
        self.assertEqual(parse_markers("12.45\n15\n16.28", 4000), [765.0, 900.0, 988.0])
        long_list = "\n".join(f"{minute}.15" for minute in range(1, 18))
        self.assertEqual(len(parse_markers(long_list, 4800)), 17)
        for raw in ("", "1:99", "1:02:99", "abc", "00:05\n00:10", "11:00"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                parse_markers(raw, 600)
        with self.assertRaises(ValueError):
            parse_markers("1:00", float("nan"))

    def test_guidance_selects_nearby_distinct_moments(self) -> None:
        candidates = [candidate(95, 120, 90), candidate(101, 125, 80),
                      candidate(300, 325, 85)]
        picked = near_markers(candidates, [100, 310])
        self.assertEqual([(item.start, item.end) for item in picked], [(95, 120), (300, 325)])
        with self.assertRaises(ValueError):
            near_markers([candidate(100, 125, 80)], [170])
        with self.assertRaises(ValueError):
            near_markers(candidates, [200])
        many = [candidate(float(i * 60), float(i * 60 + 20), float(60 + i)) for i in range(17)]
        self.assertEqual(len(near_markers(many, [float(i * 60 + 5) for i in range(17)])), 10)
        self.assertEqual(len(near_markers(many, [float(i * 60 + 5) for i in range(17)], limit=17)), 17)
        self.assertEqual(near_markers([candidate(100, 120, 90), candidate(165, 190, 55)],
                                      [170])[0].start, 165)

    def test_guided_clip_continues_to_later_natural_pause(self) -> None:
        words = [Word(float(i), float(i) + 0.5, f"word{i}") for i in range(38)]
        words[37] = Word(37, 37.5, "finish.")
        short = Candidate(0, 20.5, "opening", 80, (), tuple(words[:21]))
        extended = near_markers([short], [0], transcript_words=words)[0]
        self.assertEqual(extended.end, 37.5)
        self.assertGreaterEqual(extended.end - extended.start, 30)
        self.assertLessEqual(extended.end - extended.start, 40)


if __name__ == "__main__":
    unittest.main()
