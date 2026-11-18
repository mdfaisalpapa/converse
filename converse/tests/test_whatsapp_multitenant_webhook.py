import unittest
from unittest.mock import MagicMock, patch
import json
import frappe

if not hasattr(frappe.local, "db") or frappe.local.db is None:
    frappe.local.db = MagicMock()

from converse.channels.whatsapp.adapter import whatsapp_webhook, WhatsAppChannelAdapter
from converse.converse.doctype.bot_channel.bot_channel import BotChannel


class TestWhatsAppWebhookMultiTenant(unittest.TestCase):
    def setUp(self):
        self.raw_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "id": "1000",
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "metadata": {
                                    "display_phone_number": "15550269223",
                                    "phone_number_id": "1428481243686640"
                                },
                                "contacts": [{"profile": {"name": "Test User"}, "wa_id": "919876543210"}],
                                "messages": [
                                    {
                                        "from": "919876543210",
                                        "id": "wamid.HBgL",
                                        "timestamp": "1731920000",
                                        "text": {"body": "egs"},
                                        "type": "text"
                                    }
                                ]
                            },
                            "field": "messages"
                        }
                    ]
                }
            ]
        }

    @patch("requests.post")
    @patch("converse.channels.gateway.get_channel_gateway")
    @patch("converse.converse.doctype.bot_channel.bot_channel.BotChannel.get_channel_by_deployment")
    def test_webhook_routes_to_egs_passthrough(self, mock_get_channel, mock_get_gateway, mock_post):
        mock_channel = MagicMock()
        mock_channel.enable_multi_tenancy = 1
        mock_channel.routing_rules = [
            {
                "priority": 1,
                "tenant_name": "Dream Big EGS",
                "trigger_keywords": "EGS, STUDENT",
                "target_type": "External Webhook Passthrough",
                "webhook_url": "http://egs.localhost:8080/api/method/dreambig_egs.bot_engine.api.bot_webhook?platform=whatsapp"
            }
        ]
        mock_channel.default_target_type = "Internal Bot Deployment"
        mock_channel.default_target_deployment = "kvc3-dep"
        mock_get_channel.return_value = mock_channel

        # Mock adapter
        adapter = WhatsAppChannelAdapter()
        mock_gateway = MagicMock()
        mock_gateway.get_adapter.return_value = adapter
        mock_get_gateway.return_value = mock_gateway

        mock_post_resp = MagicMock()
        mock_post_resp.status_code = 200
        mock_post.return_value = mock_post_resp

        frappe.local.request = MagicMock()
        frappe.local.request.method = "POST"
        frappe.local.request.headers = {}
        frappe.local.request.get_json.return_value = self.raw_payload
        frappe.local.request.args = {}
        frappe.local.form_dict = {}

        result = whatsapp_webhook(deployment_key="whatsapp-ch")

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["routed_to"], "Dream Big EGS")
        self.assertEqual(result["passthrough_status"], 200)
        mock_post.assert_called_once()
        self.assertIn("dreambig_egs", mock_post.call_args[0][0])
        mock_gateway.process_and_execute.assert_not_called()


if __name__ == "__main__":
    unittest.main()
