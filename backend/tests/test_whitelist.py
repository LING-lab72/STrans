import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.services import whitelist
from app.services.whitelist import WhitelistStore, normalize_plate


class WhitelistStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = WhitelistStore(Path(self.temporary_directory.name) / "whitelist.db")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_normalize_plate_trims_separators_and_repairs_known_alias(self):
        self.assertEqual(normalize_plate(" 京-hf7912n "), "京H7912N")

    def test_upsert_persists_normalized_plate_and_delete_removes_it(self):
        created = self.store.upsert("京-a12345", owner="测试车主", note="测试车辆")

        self.assertEqual(created["plate_no"], "京A12345")
        self.assertTrue(self.store.contains("京A12345"))
        self.assertTrue(self.store.delete(" 京-a12345 "))
        self.assertFalse(self.store.contains("京A12345"))

    def test_match_plate_accepts_a_close_ocr_result_with_same_region_and_tail(self):
        self.store.upsert("京A12345")

        self.assertEqual(self.store.match_plate("京A02345"), "京A12345")

    def test_blank_plate_is_rejected_without_writing_a_record(self):
        with self.assertRaisesRegex(ValueError, "plate_no is required"):
            self.store.upsert("  -  ")

    def test_decide_plate_uses_the_active_store_for_allow_and_deny(self):
        self.store.upsert("京A12345")

        with patch.object(whitelist, "whitelist_store", self.store):
            allowed = whitelist.decide_plate("京A12345", confidence=0.2)
            denied = whitelist.decide_plate("京Z99999", confidence=0.99)

        self.assertTrue(allowed.whitelist_status)
        self.assertEqual(allowed.gate_action, "allow")
        self.assertFalse(denied.whitelist_status)
        self.assertEqual(denied.gate_action, "deny")


if __name__ == "__main__":
    unittest.main()
