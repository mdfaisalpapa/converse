"""REST Connectors package."""

from converse.connectors.rest.generic import GenericRestConnector
from converse.connectors.rest.frappe_connector import FrappeRestConnector

__all__ = ["GenericRestConnector", "FrappeRestConnector"]
