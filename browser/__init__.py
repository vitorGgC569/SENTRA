"""
Browser Automation & Multi-Session Management for AutonomousInfinityAI.
"""
from .session import BrowserSession
from .pool import BrowserPool
from .site_adapter import ChatSiteAdapter
from .response_capture import ResponseCapture

__all__ = ["BrowserSession", "BrowserPool", "ChatSiteAdapter", "ResponseCapture"]
