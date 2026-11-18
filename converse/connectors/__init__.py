"""External system connectors module.

Strict Architectural Rule:
Do not import `frappe` here.
"""
from converse.connectors.base import BaseConnector
from converse.connectors.rest.generic import GenericRestConnector
from converse.connectors.rest.frappe_connector import FrappeRestConnector

__all__ = ["BaseConnector", "GenericRestConnector", "FrappeRestConnector"]
