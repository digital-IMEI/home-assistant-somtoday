"""Regression checks for the bundled setup translations."""
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "somtoday"

class TranslationTests(unittest.TestCase):
    def test_login_instructions_exist_in_each_supported_language(self):
        source = json.loads((ROOT / "strings.json").read_text())
        for language in ("en", "nl"):
            with self.subTest(language=language):
                data = json.loads((ROOT / "translations" / f"{language}.json").read_text())
                step = data["config"]["step"]["authorize"]
                self.assertIn("]({authorize_url})", step["description"])
                self.assertIn("code=", step["description"])
                self.assertIn("state=", step["description"])
                self.assertTrue(step["data"]["callback_url"])
                self.assertTrue(data["config"]["step"]["user"]["data"]["organization"])
        self.assertEqual(source, json.loads((ROOT / "translations/en.json").read_text()))

if __name__ == "__main__":
    unittest.main()
