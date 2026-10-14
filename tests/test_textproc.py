import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from gutenread import catalog, textproc  # noqa: E402

RAW = (
    "Header text\n*** START OF THE PROJECT GUTENBERG EBOOK TEST BOOK ***\n"
    "It was _the_ best--of times, it was the worst. [Illustration: a cat]\n"
    "* * * * *\nThe end.\n*** END OF THE PROJECT GUTENBERG EBOOK TEST BOOK ***\nLicense text\n"
)


class TextProcTests(unittest.TestCase):
    def test_strip_boilerplate(self):
        body = textproc.strip_boilerplate(RAW)
        self.assertNotIn("Header", body)
        self.assertNotIn("License", body)
        self.assertIn("best", body)

    def test_prepare(self):
        words = textproc.prepare(RAW)
        self.assertEqual(words[:6], ["It", "was", "the", "best", "of", "times,"])
        self.assertNotIn("*", words)
        self.assertNotIn("[Illustration:", words)
        self.assertEqual(words[-2:], ["The", "end."])

    def test_pivot(self):
        self.assertEqual(textproc.split_pivot("a"), ("", "a", ""))
        self.assertEqual(textproc.split_pivot("word"), ("w", "o", "rd"))
        self.assertEqual(textproc.split_pivot("\u201cHello,"), ("\u201cH", "e", "llo,"))
        self.assertEqual(textproc.split_pivot(""), ("", "", ""))

    def test_delay(self):
        base = textproc.word_delay_ms("cat", 300)
        self.assertEqual(base, 200)
        self.assertGreater(textproc.word_delay_ms("cat.", 300), base)
        self.assertEqual(textproc.word_delay_ms("cat.", 300, punctuation=False), base)
        self.assertGreater(textproc.word_delay_ms("extraordinary", 300), base)

    def test_catalog_helpers(self):
        self.assertEqual(catalog._flip("Austen, Jane"), "Jane Austen")
        self.assertEqual(catalog._flip("Anonymous"), "Anonymous")
        formats = {"text/html": "a.html", "text/plain; charset=us-ascii": "a.txt",
                   "text/plain; charset=utf-8": "u.txt", "application/zip": "a.zip"}
        self.assertEqual(catalog.pick_text_url(formats), "u.txt")
        self.assertIsNone(catalog.pick_text_url({"text/html": "a.html"}))


if __name__ == "__main__":
    unittest.main()
