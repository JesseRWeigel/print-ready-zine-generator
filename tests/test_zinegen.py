import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import zinegen


class LayoutTests(unittest.TestCase):
    def test_eight_page_saddle_order(self):
        self.assertEqual(
            zinegen.saddle_spreads(8),
            [
                {"sheet": 1, "side": "front", "left": 8, "right": 1},
                {"sheet": 1, "side": "back", "left": 2, "right": 7},
                {"sheet": 2, "side": "front", "left": 6, "right": 3},
                {"sheet": 2, "side": "back", "left": 4, "right": 5},
            ],
        )

    def test_saddle_order_covers_every_page_once(self):
        placements = zinegen.saddle_spreads(12)
        pages = [value for spread in placements for value in (spread["left"], spread["right"])]
        self.assertEqual(sorted(pages), list(range(1, 13)))

    def test_saddle_rejects_invalid_signature(self):
        for count in (0, 2, 6, 9):
            with self.subTest(count=count), self.assertRaises(ValueError):
                zinegen.saddle_spreads(count)

    def test_mini_panel_order_and_rotation(self):
        placements = zinegen.mini_panels()
        self.assertEqual([item["page"] for item in placements], [5, 4, 3, 2, 6, 7, 8, 1])
        self.assertEqual([item["rotation"] for item in placements], [180] * 4 + [0] * 4)


class InputTests(unittest.TestCase):
    def test_latex_escape_handles_control_characters(self):
        escaped = zinegen.latex_escape("one_thing & 50% {safe} " + "\\")
        self.assertEqual(
            escaped,
            r"one\_thing \& 50\% \{safe\} \textbackslash{}",
        )

    def test_validation_rejects_missing_articles(self):
        with self.assertRaisesRegex(zinegen.BuildError, "articles"):
            zinegen.validate_publication({"title": "Empty", "articles": []})

    def test_validation_rejects_non_text_body(self):
        with self.assertRaisesRegex(zinegen.BuildError, "body"):
            zinegen.validate_publication(
                {"title": "Issue", "articles": [{"title": "Entry", "body": ["wrong"]}]}
            )

    def test_unsupported_unicode_returns_clean_build_error(self):
        publication = {
            "title": "Glyph probe",
            "articles": [
                {
                    "title": "Mixed text",
                    "body": "Smart quotes, an en\u2013dash, an emoji \U0001f9f5, \u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac, and \u65e5\u672c\u8a9e.",
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="zine-unicode-") as temporary:
            root = Path(temporary)
            input_path = root / "input.json"
            input_path.write_text(json.dumps(publication, ensure_ascii=False), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(Path(__file__).resolve().parents[1] / "zinegen.py"),
                    str(input_path),
                    "--output",
                    str(root / "output"),
                    "--mode",
                    "saddle",
                ],
                text=True,
                capture_output=True,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("error: pdfLaTeX failed", result.stderr)
        self.assertNotIn("Traceback", result.stderr)


if __name__ == "__main__":
    unittest.main()
