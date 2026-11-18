# Copyright (c) 2026, Converse and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from frappe import _


class ChatbotIntegration(Document):
    def validate(self):
        if self.base_url:
            self.base_url = self.base_url.rstrip("/")

    def on_rename(self, new, old, merge=False):
        """Automatically rename child Integration Actions when the integration is renamed."""
        old_prefix = f"{old}-"
        new_prefix = f"{new}-"

        actions = frappe.get_all(
            "Integration Action",
            filters={"name": ["like", f"{old_prefix}%"]},
            pluck="name",
        )

        for old_action_name in actions:
            new_action_name = old_action_name.replace(old_prefix, new_prefix, 1)
            frappe.rename_doc("Integration Action", old_action_name, new_action_name, force=True)
            frappe.db.set_value("Action Execution", {"action": old_action_name}, "action", new_action_name)

