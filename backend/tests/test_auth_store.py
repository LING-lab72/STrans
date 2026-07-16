import tempfile
import unittest
from pathlib import Path

from app.services.auth_store import AuthStore
from app.services.auth import AuthStore as CompatibilityAuthStore


class AuthStoreTests(unittest.TestCase):
    def test_legacy_auth_module_reexports_the_active_store(self):
        self.assertIs(CompatibilityAuthStore, AuthStore)

    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.store = AuthStore(Path(self.temporary_directory.name) / "auth.db")

    def tearDown(self):
        self.temporary_directory.cleanup()

    def test_create_authenticate_and_session_round_trip(self):
        created = self.store.create_user("tester", "secret12")
        authenticated = self.store.authenticate("tester", "secret12")
        token = self.store.create_session(created["id"])

        self.assertEqual(authenticated["username"], "tester")
        self.assertEqual(self.store.get_user_by_token(token)["id"], created["id"])

    def test_wrong_password_and_disabled_user_cannot_authenticate(self):
        created = self.store.create_user("tester", "secret12")
        token = self.store.create_session(created["id"])

        self.assertIsNone(self.store.authenticate("tester", "wrong-password"))
        disabled = self.store.update_user(created["id"], enabled=False)

        self.assertFalse(disabled["enabled"])
        self.assertIsNone(self.store.authenticate("tester", "secret12"))
        self.assertIsNone(self.store.get_user_by_token(token))

    def test_password_change_invalidates_existing_sessions(self):
        created = self.store.create_user("tester", "secret12")
        token = self.store.create_session(created["id"])

        self.store.change_password(created["id"], "secret12", "updated12")

        self.assertIsNone(self.store.get_user_by_token(token))
        self.assertIsNone(self.store.authenticate("tester", "secret12"))
        self.assertEqual(self.store.authenticate("tester", "updated12")["username"], "tester")

    def test_captcha_is_case_insensitive_and_single_use(self):
        captcha = self.store.new_captcha()
        with self.store._connect() as connection:
            code = connection.execute(
                "SELECT code FROM login_captcha WHERE captcha_id = ?",
                (captcha["captcha_id"],),
            ).fetchone()["code"]

        self.assertTrue(self.store.verify_captcha(captcha["captcha_id"], code.lower()))
        self.assertFalse(self.store.verify_captcha(captcha["captcha_id"], code))

    def test_audit_entries_are_returned_newest_first(self):
        self.store.add_audit("admin", "first")
        self.store.add_audit("admin", "second", "target", "detail")

        entries = self.store.list_audit()

        self.assertEqual(entries[0]["action"], "second")
        self.assertEqual(entries[0]["target"], "target")

    def test_first_boot_requires_an_explicit_admin_password(self):
        database = Path(self.temporary_directory.name) / "missing-password.db"

        with self.assertRaisesRegex(RuntimeError, "STRANS_ADMIN_PASSWORD"):
            AuthStore(database, admin_password=None)


if __name__ == "__main__":
    unittest.main()
