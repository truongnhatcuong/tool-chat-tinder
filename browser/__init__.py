"""Browser package exports."""
from browser.manager import BrowserManager
from browser.tinder import TinderBrowser
from browser.selectors import TINDER_SELECTORS, get_selector
from browser.dom_inspector import DOMInspector
from browser.match_scanner import MatchScanner
from browser.message_detector import MessageDetector
from browser.profile_reader import ProfileReader
from browser.sender import MessageSender, ConversationMismatchError, SenderVerificationError

__all__ = [
    "BrowserManager",
    "TinderBrowser",
    "TINDER_SELECTORS",
    "get_selector",
    "DOMInspector",
    "MatchScanner",
    "MessageDetector",
    "ProfileReader",
    "MessageSender",
    "ConversationMismatchError",
    "SenderVerificationError"
]
