from __future__ import annotations

import unittest

from core import Candidate, Word, generate_candidates, select_clips, similarity
from pipeline import validate_youtube_url


class AutoClipLogicTests(unittest.TestCase):
    def test_url_accepts_youtube_and_rejects_lookalike_hosts(self) -> None:
        self.assertEqual(validate_youtube_url(" https://youtu.be/abc123 "), "https://youtu.be/abc123")
        self.assertEqual(validate_youtube_url("https://www.youtube.com/watch?v=abc123"),
                         "https://www.youtube.com/watch?v=abc123")
        for url in ("https://youtube.com.evil.test/watch?v=1", "file:///video.mp4", "https://youtube.com/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_youtube_url(url)

    def test_word_boundary_validation(self) -> None:
        with self.assertRaises(ValueError):
            Word(3, 2, "hello")
        with self.assertRaises(ValueError):
            Word(0, 1, " ")

    def test_select_complete_nonoverlapping_nonrepetitive_moments(self) -> None:
        scripts = [
            "The biggest mistake people make is confusing attention with trust. Because trust grows when you explain the reason for your decisions. Instead of chasing a giant indifferent audience, you should earn a small honest one. That means people return when they need you.",
            "Here is the key to learning quickly. You should test one idea with a real customer, listen to the answer, and change the next experiment. Instead of guessing for a month, you need to measure what people actually choose.",
            "My advice is to start by writing down the problem. For example, if customers leave after a week, ask what they expected and what was missing. Then fix the gap you can measure instead of changing everything at once.",
        ]
        words = []
        current = 0.0
        for script in scripts:
            for token in script.split():
                words.append(Word(current, current + 0.34, token))
                current += 0.4
            current += 4.0
        candidates = generate_candidates(words)
        chosen = select_clips(candidates)
        self.assertGreaterEqual(len(chosen), 2)
        self.assertLessEqual(len(chosen), 3)
        for clip in chosen:
            self.assertGreaterEqual(clip.end - clip.start, 10)
            self.assertLessEqual(clip.end - clip.start, 40)
            self.assertTrue(clip.text.endswith("."))
        for i, left in enumerate(chosen):
            for right in chosen[i + 1:]:
                self.assertLessEqual(min(left.end, right.end) - max(left.start, right.start), 1)
                self.assertLessEqual(similarity(left.text, right.text), 0.48)

    def test_long_unpunctuated_speech_still_yields_late_insight(self) -> None:
        """The reported livestream lost punctuation after its opening minutes."""
        early = "yeah that was great and then we talked about it for a while and everyone said okay right"
        late = ("if you take two losses in a row stop trading for the day because protecting capital "
                "matters more than forcing another trade you should stop instead of chasing a loss "
                "that means the market will still be there tomorrow")
        words: list[Word] = []
        for start, script in ((0.0, early), (1800.0, late)):
            current = start
            for token in script.split():
                words.append(Word(current, current + 0.34, token))
                current += 0.41
        candidates = generate_candidates(words)
        chosen = select_clips(candidates)
        self.assertTrue(any(c.start >= 1800 for c in chosen), "Late, punctuation-free advice was ignored")
        self.assertTrue(all(c.start >= 1800 for c in chosen), "Conversation filler outranked the advice")
        self.assertTrue(all(10 <= c.end - c.start <= 40 for c in chosen))

    def test_ai_can_promote_complete_lower_heuristic_moment(self) -> None:
        words = [Word(float(i), float(i) + 0.5, f"word{i}") for i in range(20)]
        candidate = Candidate(0, 20, "A complete useful idea about managing risk.", 70, [], words)
        self.assertEqual(select_clips([candidate]), [])
        chosen = select_clips([candidate], extra_score=lambda _: 12)
        self.assertEqual(len(chosen), 1)
        self.assertEqual(chosen[0].score, 82)


if __name__ == "__main__":
    unittest.main()
