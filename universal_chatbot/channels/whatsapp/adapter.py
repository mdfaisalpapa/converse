"""WhatsApp Channel Adapter.

Handles normalization of Meta WhatsApp Cloud API webhook events into the common
message protocol, and formatting of outbound messages into WhatsApp Graph API requests.
"""

from typing import Any, Dict, List, Optional, Union
import re
import uuid
import requests

from universal_chatbot.channels.base import BaseChannelAdapter
from universal_chatbot.core.exceptions import SecurityValidationError
from universal_chatbot.core.protocol import (
    EngineResponse,
    IncomingMessage,
    OutgoingResponse,
    SessionStatus,
)


class WhatsAppChannelAdapter(BaseChannelAdapter):
    """Adapter for Meta WhatsApp Cloud API communication."""

    channel_type = "whatsapp"

    def normalize_message(
        self, raw_payload: Dict[str, Any], headers: Optional[Dict[str, str]] = None
    ) -> IncomingMessage:
        """Parse raw incoming Meta WhatsApp Cloud API payload into IncomingMessage protocol."""
        if not isinstance(raw_payload, dict):
            raise SecurityValidationError("Invalid payload format. Expected JSON dictionary.")

        headers = headers or {}

        # 1. Deployment ID
        deployment_id = (
            raw_payload.get("deployment_key")
            or raw_payload.get("deployment_id")
            or headers.get("x-deployment-key")
            or "whatsapp_default"
        )

        from_number = ""
        text = ""
        msg_id = ""
        phone_number_id = ""
        display_phone_number = ""
        profile_name = ""

        # 2. Check for standard Meta Cloud API structure: entry[0].changes[0].value
        entry = raw_payload.get("entry", [])
        if entry and isinstance(entry, list):
            first_entry = entry[0] if isinstance(entry[0], dict) else {}
            changes = first_entry.get("changes", [])
            if changes and isinstance(changes, list):
                first_change = changes[0] if isinstance(changes[0], dict) else {}
                value = first_change.get("value", {})
                if isinstance(value, dict):
                    # Metadata
                    meta = value.get("metadata", {})
                    phone_number_id = str(meta.get("phone_number_id", ""))
                    display_phone_number = str(meta.get("display_phone_number", ""))

                    # Contacts
                    contacts = value.get("contacts", [])
                    if contacts and isinstance(contacts, list):
                        contact_obj = contacts[0] if isinstance(contacts[0], dict) else {}
                        profile_name = contact_obj.get("profile", {}).get("name", "")
                        from_number = contact_obj.get("wa_id", "")

                    # Messages
                    messages = value.get("messages", [])
                    if messages and isinstance(messages, list):
                        msg_obj = messages[0] if isinstance(messages[0], dict) else {}
                        from_number = from_number or msg_obj.get("from", "")
                        msg_id = msg_obj.get("id", "")
                        mtype = msg_obj.get("type", "text")

                        if mtype == "text":
                            text = msg_obj.get("text", {}).get("body", "")
                        elif mtype == "interactive":
                            interactive = msg_obj.get("interactive", {})
                            itype = interactive.get("type")
                            if itype == "button_reply":
                                btn = interactive.get("button_reply", {})
                                text = btn.get("id") or btn.get("title", "")
                            elif itype == "list_reply":
                                lst = interactive.get("list_reply", {})
                                text = lst.get("id") or lst.get("title", "")
                        elif mtype == "button":
                            btn = msg_obj.get("button", {})
                            text = btn.get("payload") or btn.get("text", "")
                        elif mtype in ("image", "document", "audio", "video"):
                            text = msg_obj.get(mtype, {}).get("caption", "")

        # 3. Fallback for flat dictionary payloads (mock/test payloads)
        if not from_number:
            from_number = (
                raw_payload.get("from")
                or raw_payload.get("external_user_id")
                or raw_payload.get("wa_id")
                or raw_payload.get("sender_id")
                or ""
            )

        if not text:
            text = (
                raw_payload.get("text")
                or raw_payload.get("content")
                or (raw_payload.get("message", {}).get("text") if isinstance(raw_payload.get("message"), dict) else "")
                or ""
            )

        if not msg_id:
            msg_id = raw_payload.get("message_id") or str(uuid.uuid4())

        if not phone_number_id:
            phone_number_id = raw_payload.get("phone_number_id", "")

        from_number = str(from_number).strip()
        if not from_number:
            raise SecurityValidationError("Missing required sender phone number / wa_id in WhatsApp payload.")

        # 4. Construct Protocol message and metadata
        message_dict = {
            "message_id": str(msg_id),
            "type": "text",
            "text": str(text).strip(),
            "phone_number": from_number,
        }

        meta_dict = {
            "language": raw_payload.get("language") or "en",
            "timezone": raw_payload.get("timezone") or "UTC",
            "phone_number": from_number,
            "phone_number_id": phone_number_id,
            "display_phone_number": display_phone_number,
            "profile_name": profile_name,
            "channel": self.channel_type,
        }

        extra = raw_payload.get("metadata")
        if isinstance(extra, dict):
            for k, v in extra.items():
                if k not in meta_dict:
                    meta_dict[k] = v

        return IncomingMessage(
            tenant_id=raw_payload.get("tenant_id"),
            bot_id=str(raw_payload.get("bot_id", "whatsapp_bot")),
            deployment_id=str(deployment_id),
            channel=self.channel_type,
            external_user_id=from_number,
            conversation_id=raw_payload.get("conversation_id"),
            message=message_dict,
            metadata=meta_dict,
        )

    def format_response(
        self,
        response: Union[OutgoingResponse, EngineResponse, Dict[str, Any]],
        recipient: Optional[str] = None,
        **kwargs,
    ) -> Dict[str, Any]:
        """Convert standard conversation engine response into Meta WhatsApp Cloud API payload."""
        to_phone = str(recipient or kwargs.get("to") or kwargs.get("recipient_phone") or "").lstrip("+").strip()

        text = ""
        actions: List[Dict[str, Any]] = []

        if isinstance(response, OutgoingResponse):
            text = response.response.get("text", "")
            actions = response.actions
        elif isinstance(response, EngineResponse):
            msgs = [m.to_dict() for m in response.messages]
            text = "\n\n".join([m["content"] for m in msgs if m.get("content")]) if msgs else ""
        elif isinstance(response, dict):
            raw_msgs = response.get("messages", [])
            if raw_msgs:
                text_parts = [m.get("text", "") for m in raw_msgs if m.get("text")]
                text = "\n\n".join(text_parts) if text_parts else ""
                for m in raw_msgs:
                    if m.get("options"):
                        for opt in m["options"]:
                            actions.append({
                                "label": opt.get("label"),
                                "value": opt.get("value"),
                            })
            else:
                text = response.get("response", {}).get("text", "")
            if not actions and response.get("actions"):
                actions = response["actions"]

        text = text or "..."

        # Check if the message contains an embedded URL link for portal access (e.g., SSO link)
        # In WhatsApp Cloud API, CTA URL buttons cannot be combined with reply buttons in one interactive message.
        # So we format a native CTA URL interactive card and bundle any subsequent navigation buttons for split delivery.
        url_match = re.search(r"https?://[^\s\)\"\>]+", text)
        if url_match and ("authenticate_sso" in url_match.group(0) or "standalone=1" in url_match.group(0)):
            target_url = url_match.group(0)
            # Clean up the raw link block from the message body for a crisp presentation
            clean_text = re.sub(
                r"(\n*🔗[^\n]+\n*https?://[^\s\)\"\>]+\n*(\_\([^\)]+\)\_)?)|(https?://[^\s\)\"\>]+)",
                "",
                text,
            ).strip()
            # If prompt has a title line like `🚗 *Vehicles (22 Pending)*`, extract header
            header_text = None
            lines = [l.strip() for l in clean_text.split("\n") if l.strip()]
            if lines and ("*" in lines[0] or len(lines[0]) <= 60):
                first_line = lines[0].replace("*", "")
                if len(first_line) <= 60:
                    header_text = first_line
                    body_text = "\n".join(lines[1:]).strip() if len(lines) > 1 else "Tap the button below to open this portal section in your browser:"
                else:
                    body_text = clean_text
            else:
                body_text = clean_text or "Tap the button below to open this portal section in your browser:"

            cta_payload = {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": str(to_phone),
                "type": "interactive",
                "interactive": {
                    "type": "cta_url",
                    "body": {"text": body_text[:1024]},
                    "footer": {"text": "Secure 1-Click Access (15 min valid)"},
                    "action": {
                        "name": "cta_url",
                        "parameters": {
                            "display_text": "🌐 Open Portal ↗"[:20],
                            "url": target_url,
                        },
                    },
                },
            }
            if header_text:
                cta_payload["interactive"]["header"] = {"type": "text", "text": header_text[:60]}

            # If there are navigation actions (e.g. Back to Committee, Main Menu), prepare secondary nav message
            if actions:
                buttons = []
                for idx, act in enumerate(actions[:3]):
                    val = str(act.get("value") or act.get("label") or f"opt_{idx}")[:256]
                    lbl = str(act.get("label") or act.get("value") or f"Option {idx+1}")[:20]
                    buttons.append({
                        "type": "reply",
                        "reply": {
                            "id": val,
                            "title": lbl,
                        },
                    })
                nav_payload = {
                    "messaging_product": "whatsapp",
                    "recipient_type": "individual",
                    "to": str(to_phone),
                    "type": "interactive",
                    "interactive": {
                        "type": "button",
                        "body": {"text": "Navigation:"},
                        "action": {"buttons": buttons},
                    },
                }
                cta_payload["_extra_messages"] = [nav_payload]

            return cta_payload

        # Interactive Button message (Up to 3 buttons allowed by WhatsApp Cloud API)
        if actions and 1 <= len(actions) <= 3:
            buttons = []
            for idx, act in enumerate(actions[:3]):
                val = str(act.get("value") or act.get("label") or f"opt_{idx}")[:256]
                lbl = str(act.get("label") or act.get("value") or f"Option {idx+1}")[:20]
                buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": val,
                        "title": lbl,
                    },
                })
            return {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": str(to_phone),
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {"buttons": buttons},
                },
            }

        # Interactive List message (When more than 3 buttons)
        elif actions and len(actions) > 3:
            rows = []
            for idx, act in enumerate(actions[:10]):
                val = str(act.get("value") or act.get("label") or f"opt_{idx}")[:200]
                lbl = str(act.get("label") or act.get("value") or f"Option {idx+1}")[:24]
                rows.append({
                    "id": val,
                    "title": lbl,
                })
            return {
                "messaging_product": "whatsapp",
                "recipient_type": "individual",
                "to": str(to_phone),
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": text},
                    "action": {
                        "button": "Select Option",
                        "sections": [
                            {
                                "title": "Options",
                                "rows": rows,
                            }
                        ],
                    },
                },
            }

        # Standard Text message
        return {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to_phone),
            "type": "text",
            "text": {
                "preview_url": False,
                "body": text,
            },
        }

    def send_whatsapp_message(
        self, phone_number_id: str, access_token: str, payload: Dict[str, Any]
    ) -> requests.Response:
        """Transmit formatted message payload to Meta WhatsApp Cloud API."""
        if not phone_number_id:
            raise ValueError("phone_number_id is required to send WhatsApp message.")
        if not access_token:
            raise ValueError("access_token is required to send WhatsApp message.")

        url = f"https://graph.facebook.com/v19.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        return response


def whatsapp_webhook(deployment_key: Optional[str] = None):
    """Whitelisted Frappe webhook endpoint handling Meta WhatsApp verification and messages."""
    import frappe
    from werkzeug.wrappers import Response
    from universal_chatbot.channels.gateway import get_channel_gateway
    from universal_chatbot.universal_chatbot.doctype.bot_channel.bot_channel import BotChannel

    gateway = get_channel_gateway()
    request_method = frappe.request.method if getattr(frappe, "request", None) else "POST"

    # 1. Handle Meta Webhook Verification Handshake (GET)
    if request_method == "GET":
        args = dict(getattr(frappe.request, "args", {}) or frappe.form_dict)
        hub_mode = args.get("hub.mode")
        hub_challenge = args.get("hub.challenge")
        hub_verify_token = args.get("hub.verify_token")

        if hub_mode == "subscribe" and hub_challenge:
            # Validate verify token against deployment or channels
            dep_key = deployment_key or args.get("deployment_key")
            valid = False
            if dep_key:
                channel_doc = BotChannel.get_channel_by_deployment(dep_key, channel_type="WhatsApp")
                if channel_doc:
                    creds = channel_doc.get_credentials()
                    if creds.get("verify_token") == hub_verify_token:
                        valid = True
            else:
                # Check if any WhatsApp channel matches the verify token
                matching = frappe.db.get_value(
                    "Bot Channel",
                    {"channel_type": "WhatsApp", "whatsapp_verify_token": hub_verify_token, "is_enabled": 1},
                    "name",
                )
                if matching:
                    valid = True

            if valid or not hub_verify_token:
                return Response(hub_challenge, mimetype="text/plain", status=200)

        # Return 403 Forbidden on invalid verify token
        return Response("Forbidden", mimetype="text/plain", status=403)

    # 2. Handle Incoming WhatsApp Message (POST)
    headers = dict(getattr(frappe.local, "request", None) and frappe.local.request.headers or {})
    raw_payload = frappe.request.get_json(force=True, silent=True) or dict(frappe.form_dict)

    # Acknowledge Meta status updates (sent, delivered, read) without processing
    entry = raw_payload.get("entry", [])
    if entry and isinstance(entry, list):
        first_entry = entry[0] if isinstance(entry[0], dict) else {}
        changes = first_entry.get("changes", [])
        if changes and isinstance(changes, list):
            val = changes[0].get("value", {})
            if isinstance(val, dict) and "statuses" in val and not val.get("messages"):
                return {"status": "ok", "message": "status event acknowledged"}

    dep_key = deployment_key or frappe.request.args.get("deployment_key") or raw_payload.get("deployment_key")

    result = gateway.process_and_execute(
        channel_type="whatsapp",
        raw_payload=raw_payload,
        headers=headers,
        deployment_key=dep_key,
    )

    deployment = result.get("deployment")
    channel_doc = BotChannel.get_channel_by_deployment(deployment.name, channel_type="WhatsApp")
    if channel_doc:
        creds = channel_doc.get_credentials()
        phone_number_id = creds.get("phone_number_id")
        access_token = creds.get("access_token")

        if phone_number_id and access_token and result.get("formatted_response"):
            adapter = gateway.get_adapter("whatsapp")
            if isinstance(adapter, WhatsAppChannelAdapter):
                try:
                    main_payload = dict(result["formatted_response"])
                    extra_messages = main_payload.pop("_extra_messages", [])
                    resp = adapter.send_whatsapp_message(
                        phone_number_id=phone_number_id,
                        access_token=access_token,
                        payload=main_payload,
                    )
                    if resp.status_code >= 400:
                        frappe.log_error(
                            f"Meta WhatsApp API returned HTTP {resp.status_code}: {resp.text}\nPayload: {main_payload}",
                            "WhatsApp Outbound Send Error",
                        )
                    # Send any secondary split-delivery messages (e.g. navigation buttons)
                    for extra in extra_messages:
                        try:
                            adapter.send_whatsapp_message(
                                phone_number_id=phone_number_id,
                                access_token=access_token,
                                payload=extra,
                            )
                        except Exception as extra_err:
                            frappe.log_error(f"Failed to send extra WhatsApp message: {extra_err}", "WhatsApp Send Extra Exception")
                except Exception as e:
                    frappe.log_error(f"Failed to send WhatsApp message: {e}", "WhatsApp Send Exception")

    return {"status": "ok", "conversation_id": result.get("conversation_id")}


try:
    import frappe
    whatsapp_webhook = frappe.whitelist(allow_guest=True)(whatsapp_webhook)
except Exception:
    pass
