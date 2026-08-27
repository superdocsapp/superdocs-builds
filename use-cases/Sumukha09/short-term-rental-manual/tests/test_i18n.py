import unittest

from strgen.i18n import LANGUAGES, STRINGS, T


class TestTranslations(unittest.TestCase):
    def test_all_languages_share_key_parity_with_english(self):
        reference = set(STRINGS["en"])
        for lang in LANGUAGES:
            missing = reference - set(STRINGS[lang])
            self.assertFalse(missing, f"{lang} missing keys: {sorted(missing)}")

    def test_fallback_chain(self):
        t = T("zz")          # unknown language falls back to English catalog
        self.assertEqual(t("sec_rules"), STRINGS["en"]["sec_rules"])

    def test_month_year_localized(self):
        self.assertEqual(T("fr").month_year(2026, 8), "août 2026")
        self.assertEqual(T("es").month_year(2026, 8), "agosto 2026")


if __name__ == "__main__":
    unittest.main()
