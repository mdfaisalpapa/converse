"""Channels module for normalizing external platform messaging.

Strict Architectural Rule:
Do not import `frappe` here.
"""

from converse.channels.base import BaseChannelAdapter
from converse.channels.gateway import ChannelGateway, get_channel_gateway
from converse.channels.web.adapter import WebChannelAdapter
from converse.channels.telegram.adapter import TelegramChannelAdapter
from converse.channels.whatsapp.adapter import WhatsAppChannelAdapter

__all__ = [
    "BaseChannelAdapter",
    "ChannelGateway",
    "get_channel_gateway",
    "WebChannelAdapter",
    "TelegramChannelAdapter",
    "WhatsAppChannelAdapter",
]
