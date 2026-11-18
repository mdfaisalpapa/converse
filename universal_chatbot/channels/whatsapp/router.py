"""Multi-Tenant Channel Routing Engine.

Evaluates incoming messages for multi-tenant channels according to:
1. Reset / Exit Keywords (e.g., EXIT, RESET) -> Clears active tenant
2. Sticky Session Routing -> Keeps ongoing user conversations bound to their tenant
3. Trigger Keywords (e.g., EGS, STUDENT vs KVC3, SOCIETY)
4. Silent Phone Lookup (checks Integration Action per tenant without cross-revealing)
5. Fallback Default (e.g., KVC3 AOA)
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
import frappe


def normalize_phone(phone_str: str) -> List[str]:
    """Return common variations of a phone number for lookup matching.

    e.g. '919876543210' -> ['919876543210', '+919876543210', '9876543210']
    """
    if not phone_str:
        return []
    cleaned = "".join(ch for ch in str(phone_str) if ch.isdigit() or ch == "+")
    digits_only = "".join(ch for ch in cleaned if ch.isdigit())
    
    variations = set()
    if digits_only:
        variations.add(digits_only)
        variations.add(f"+{digits_only}")
        if len(digits_only) == 12 and digits_only.startswith("91"):
            variations.add(digits_only[2:])
            variations.add(f"+91{digits_only[2:]}")
        elif len(digits_only) == 10:
            variations.add(f"91{digits_only}")
            variations.add(f"+91{digits_only}")
            variations.add(f"0{digits_only}")
            
    return list(variations)


class MultiTenantRouter:
    """Evaluates channel routing rules for multi-tenant bots."""

    def __init__(self, channel_doc):
        self.channel = channel_doc

    def resolve_target(
        self,
        from_number: str,
        message_text: str,
        raw_payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolves target routing for an incoming message.

        Returns dict:
        {
            "target_type": "Internal Bot Deployment" | "External Webhook Passthrough",
            "deployment": <deployment_name or None>,
            "webhook_url": <url or None>,
            "tenant_name": <tenant_name>,
            "session_reset": bool,
            "matched_by": "keyword" | "session" | "phone_lookup" | "default"
        }
        """
        text = (message_text or "").strip().lower()
        reset_keywords = [
            k.strip().lower()
            for k in (getattr(self.channel, "reset_keywords", "") or "EXIT, RESET").split(",")
            if k.strip()
        ]

        # 1. Check for Reset / Exit Keywords
        if text in reset_keywords:
            self._clear_active_session(from_number)
            return {
                "target_type": getattr(self.channel, "default_target_type", "Internal Bot Deployment") or "Internal Bot Deployment",
                "deployment": getattr(self.channel, "default_target_deployment", None) or getattr(self.channel, "deployment", None),
                "webhook_url": getattr(self.channel, "default_webhook_url", None),
                "tenant_name": "Default (Reset)",
                "session_reset": True,
                "matched_by": "reset",
            }

        rules = self._get_sorted_rules()

        # 2. Check Explicit Trigger Keywords
        for rule in rules:
            keywords = [
                k.strip().lower()
                for k in (rule.get("trigger_keywords") or "").split(",")
                if k.strip()
            ]
            if text in keywords:
                self._save_active_session(from_number, rule.get("tenant_name"))
                return {
                    "target_type": rule.get("target_type") or "Internal Bot Deployment",
                    "deployment": rule.get("target_deployment"),
                    "webhook_url": rule.get("webhook_url"),
                    "tenant_name": rule.get("tenant_name"),
                    "session_reset": False,
                    "matched_by": "keyword",
                }

        # 3. Check Active Sticky Session
        sticky_hours = int(getattr(self.channel, "session_sticky_hours", 24) or 24)
        active_tenant = self._get_active_session(from_number, sticky_hours)
        if active_tenant:
            for rule in rules:
                if rule.get("tenant_name") == active_tenant:
                    return {
                        "target_type": rule.get("target_type") or "Internal Bot Deployment",
                        "deployment": rule.get("target_deployment"),
                        "webhook_url": rule.get("webhook_url"),
                        "tenant_name": rule.get("tenant_name"),
                        "session_reset": False,
                        "matched_by": "session",
                    }

        # 4. Silent Phone Lookup
        matched_rule = self._lookup_by_phone(from_number, rules)
        if matched_rule:
            self._save_active_session(from_number, matched_rule.get("tenant_name"))
            return {
                "target_type": matched_rule.get("target_type") or "Internal Bot Deployment",
                "deployment": matched_rule.get("target_deployment"),
                "webhook_url": matched_rule.get("webhook_url"),
                "tenant_name": matched_rule.get("tenant_name"),
                "session_reset": False,
                "matched_by": "phone_lookup",
            }

        # 5. Fallback Default
        default_target_type = getattr(self.channel, "default_target_type", "Internal Bot Deployment") or "Internal Bot Deployment"
        default_deployment = getattr(self.channel, "default_target_deployment", None) or getattr(self.channel, "deployment", None)
        default_url = getattr(self.channel, "default_webhook_url", None)

        return {
            "target_type": default_target_type,
            "deployment": default_deployment,
            "webhook_url": default_url,
            "tenant_name": "Default Fallback",
            "session_reset": False,
            "matched_by": "default",
        }

    def _get_sorted_rules(self) -> List[Dict[str, Any]]:
        rules = getattr(self.channel, "routing_rules", []) or []
        parsed = []
        for r in rules:
            d = r.as_dict() if hasattr(r, "as_dict") else dict(r)
            parsed.append(d)
        return sorted(parsed, key=lambda x: int(x.get("priority", 999) or 999))

    def _get_active_session(self, from_number: str, sticky_hours: int) -> Optional[str]:
        if not from_number:
            return None
        try:
            contact = frappe.db.get_value("Chat Contact", {"identifier": from_number}, "name")
            if not contact:
                return None

            cutoff = datetime.now() - timedelta(hours=sticky_hours)
            conv = frappe.db.get_value(
                "Chat Conversation",
                {
                    "contact": contact,
                    "channel": getattr(self.channel, "name", "WhatsApp"),
                    "status": "Active",
                    "last_activity": [">=", cutoff],
                },
                ["name", "active_tenant"],
                as_dict=True,
            )
            if conv and conv.get("active_tenant"):
                return conv.get("active_tenant")
        except Exception as e:
            try:
                frappe.log_error(f"Error checking active session: {e}", "MultiTenantRouter")
            except Exception:
                pass
        return None

    def _save_active_session(self, from_number: str, tenant_name: str):
        if not from_number or not tenant_name:
            return
        try:
            contact = frappe.db.get_value("Chat Contact", {"identifier": from_number}, "name")
            if not contact:
                return

            active_convs = frappe.get_all(
                "Chat Conversation",
                filters={
                    "contact": contact,
                    "channel": getattr(self.channel, "name", "WhatsApp"),
                    "status": "Active",
                },
                fields=["name"],
            )
            for c in active_convs:
                frappe.db.set_value("Chat Conversation", c.name, "active_tenant", tenant_name)
        except Exception as e:
            try:
                frappe.log_error(f"Error saving active session: {e}", "MultiTenantRouter")
            except Exception:
                pass

    def _clear_active_session(self, from_number: str):
        if not from_number:
            return
        try:
            contact = frappe.db.get_value("Chat Contact", {"identifier": from_number}, "name")
            if not contact:
                return
            active_convs = frappe.get_all(
                "Chat Conversation",
                filters={
                    "contact": contact,
                    "channel": getattr(self.channel, "name", "WhatsApp"),
                    "status": "Active",
                },
                fields=["name"],
            )
            for c in active_convs:
                frappe.db.set_value("Chat Conversation", c.name, "active_tenant", None)
        except Exception as e:
            try:
                frappe.log_error(f"Error clearing active session: {e}", "MultiTenantRouter")
            except Exception:
                pass

    def _lookup_by_phone(self, from_number: str, rules: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Silently queries Integration Action for phone existence."""
        if not from_number:
            return None

        matched_rules = []
        variations = normalize_phone(from_number)

        for rule in rules:
            action_name = rule.get("phone_lookup_action")
            if not action_name:
                continue

            try:
                # If Integration Action exists, execute it
                from universal_chatbot.connectors.base import execute_integration_action
                result = execute_integration_action(
                    action_name=action_name,
                    parameters={"phone": from_number, "phone_variations": variations},
                )
                if result and result.get("found"):
                    matched_rules.append(rule)
            except Exception as e:
                frappe.log_error(
                    f"Phone lookup failed for rule {rule.get('tenant_name')}: {e}",
                    "MultiTenantRouter Phone Lookup",
                )

        # Only return a match if uniquely identified in exactly one tenant rule
        if len(matched_rules) == 1:
            return matched_rules[0]

        return None
