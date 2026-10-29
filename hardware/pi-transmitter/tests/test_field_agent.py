import unittest

from field_agent import valid_id


class FieldConsoleValidationTests(unittest.TestCase):
    def test_accepts_safe_ids(self):
        self.assertTrue(valid_id("MANIT-20261030-A"))
        self.assertTrue(valid_id("RC-20261030T010203-AB123"))

    def test_rejects_path_or_shell_characters(self):
        self.assertFalse(valid_id("../mission"))
        self.assertFalse(valid_id("hello;rm"))
        self.assertFalse(valid_id("x"))
        self.assertFalse(valid_id(" "))


if __name__ == "__main__":
    unittest.main()
