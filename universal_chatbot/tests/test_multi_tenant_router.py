import unittest
from unittest.mock import MagicMock, patch
import frappe

# Provide mock db if not bound
if not hasattr(frappe.local, "db") or frappe.local.db is None:
    frappe.local.db = MagicMock()

from universal_chatbot.channels.whatsapp.router import MultiTenantRouter, normalize_phone


class TestMultiTenantRouting(unittest.TestCase):
    def setUp(self):
        self.mock_channel = MagicMock()
        self.mock_channel.name = "WhatsApp Test Channel"
        self.mock_channel.enable_multi_tenancy = 1
        self.mock_channel.default_target_type = "Internal Bot Deployment"
        self.mock_channel.default_target_deployment = "kvc3-main-dep"
        self.mock_channel.default_webhook_url = None
        self.mock_channel.session_sticky_hours = 24
        self.mock_channel.reset_keywords = "EXIT, RESET"

        self.mock_channel.routing_rules = [
            {
                "priority": 1,
                "tenant_name": "Dream Big EGS",
                "trigger_keywords": "EGS, STUDENT, DREAMBIG",
                "target_type": "External Webhook Passthrough",
                "target_deployment": None,
                "webhook_url": "http://egs.localhost:8080/api/method/dreambig_egs.bot_engine.api.bot_webhook?platform=whatsapp",
                "phone_lookup_action": "egs_check_student",
            },
            {
                "priority": 2,
                "tenant_name": "KVC3 Resident",
                "trigger_keywords": "KVC3, FLAT, SOCIETY",
                "target_type": "Internal Bot Deployment",
                "target_deployment": "kvc3-main-dep",
                "webhook_url": None,
                "phone_lookup_action": "kvc3_check_resident",
            },
        ]
        self.router = MultiTenantRouter(self.mock_channel)

    def test_phone_normalization(self):
        variations = normalize_phone("919876543210")
        self.assertIn("919876543210", variations)
        self.assertIn("+919876543210", variations)
        self.assertIn("9876543210", variations)

        variations_10 = normalize_phone("9876543210")
        self.assertIn("9876543210", variations_10)
        self.assertIn("919876543210", variations_10)
        self.assertIn("+919876543210", variations_10)

    @patch.object(MultiTenantRouter, "_save_active_session")
    def test_explicit_keyword_egs(self, mock_save):
        res = self.router.resolve_target("919876543210", "egs")
        self.assertEqual(res["matched_by"], "keyword")
        self.assertEqual(res["tenant_name"], "Dream Big EGS")
        self.assertEqual(res["target_type"], "External Webhook Passthrough")
        self.assertIn("dreambig_egs", res["webhook_url"])
        mock_save.assert_called_once_with("919876543210", "Dream Big EGS")

    @patch.object(MultiTenantRouter, "_save_active_session")
    def test_explicit_keyword_kvc3(self, mock_save):
        res = self.router.resolve_target("919876543210", "KVC3")
        self.assertEqual(res["matched_by"], "keyword")
        self.assertEqual(res["tenant_name"], "KVC3 Resident")
        self.assertEqual(res["target_type"], "Internal Bot Deployment")
        self.assertEqual(res["deployment"], "kvc3-main-dep")
        mock_save.assert_called_once_with("919876543210", "KVC3 Resident")

    @patch.object(MultiTenantRouter, "_get_active_session", return_value="Dream Big EGS")
    def test_sticky_session_routing(self, mock_session):
        # User sends follow-up text like 'Yes' or '2'
        res = self.router.resolve_target("919876543210", "Yes")
        self.assertEqual(res["matched_by"], "session")
        self.assertEqual(res["tenant_name"], "Dream Big EGS")
        self.assertEqual(res["target_type"], "External Webhook Passthrough")

    @patch.object(MultiTenantRouter, "_clear_active_session")
    def test_reset_keyword(self, mock_clear):
        res = self.router.resolve_target("919876543210", "exit")
        self.assertTrue(res["session_reset"])
        self.assertEqual(res["matched_by"], "reset")
        mock_clear.assert_called_once_with("919876543210")

    @patch.object(MultiTenantRouter, "_save_active_session")
    @patch.object(MultiTenantRouter, "_get_active_session", return_value=None)
    @patch.object(MultiTenantRouter, "_lookup_by_phone")
    def test_silent_phone_lookup_matched(self, mock_lookup, mock_session, mock_save):
        mock_lookup.return_value = self.mock_channel.routing_rules[0]  # Matches EGS
        res = self.router.resolve_target("919876543210", "Hi")
        self.assertEqual(res["matched_by"], "phone_lookup")
        self.assertEqual(res["tenant_name"], "Dream Big EGS")
        mock_save.assert_called_once_with("919876543210", "Dream Big EGS")

    @patch.object(MultiTenantRouter, "_get_active_session", return_value=None)
    @patch.object(MultiTenantRouter, "_lookup_by_phone", return_value=None)
    def test_fallback_default_to_kvc3(self, mock_lookup, mock_session):
        res = self.router.resolve_target("919999999999", "Hello")
        self.assertEqual(res["matched_by"], "default")
        self.assertEqual(res["target_type"], "Internal Bot Deployment")
        self.assertEqual(res["deployment"], "kvc3-main-dep")


if __name__ == "__main__":
    unittest.main()
