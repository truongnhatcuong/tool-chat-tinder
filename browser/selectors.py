"""Centralized verified selector definitions for Tinder Web automation.
Verified on real Tinder live DOM session.
"""

TINDER_SELECTORS = {
    # Match & Conversation lists
    "conversation_list": [
        "a[href*='/app/messages/']",
        "div[role='tabpanel']",
        "[data-testid='conversation-list']",
        "nav[aria-label='Sidebar']",
        "aside",
        "div[class*='message']"
    ],
    "conversation_item": [
        "a[href*='/app/messages/']",
        "li[role='listitem']"
    ],
    "unread_indicator": [
        "span[class*='badge']",
        "[data-testid='unread-indicator']"
    ],
    "match_name": [
        "h3",
        "[data-testid='match-name']",
        "span"
    ],

    # Active Chat Container & Messages
    "message_container": [
        "div[role='log']",
        "[data-testid='messages-container']",
        "div[class*='message-container']"
    ],
    "incoming_message": [
        "div[class*='msg-incoming']",
        "div[class*='theirs']",
        "div[data-testid='incoming-message']"
    ],
    "outgoing_message": [
        "div[class*='msg-outgoing']",
        "div[class*='mine']",
        "div[data-testid='outgoing-message']"
    ],
    "message_timestamp": [
        "time",
        "span[class*='timestamp']"
    ],

    # Chat Input Box & Send Button (Verified against live Tinder DOM)
    "chat_input": [
        "textarea[placeholder*='Nhập tin nhắn']",
        "textarea[placeholder*='Type a message']",
        "textarea:not([aria-hidden='true'])",
        "div[contenteditable='true']"
    ],
    "send_button": [
        "button[aria-label='Gửi tin nhắn']",
        "button[type='submit']:has-text('Gửi')",
        "button[aria-label*='Send']",
        "button[type='submit']"
    ],

    # Profile Panel & Visible Information (Verified against live Tinder DOM)
    "profile_panel": [
        "aside",
        "div[aria-label*='profile']",
        "div[class*='profileCard']"
    ],
    "profile_name_age": [
        "h1[aria-label*='tuổi']",
        "h1[class*='Typs(display-1-strong)']",
        "h1"
    ],
    "profile_bio": [
        "div:has-text('Giới thiệu bản thân') + div",
        "div[class*='Typs(body-1-regular)']",
        "div[class*='bio']"
    ],
    "profile_goal": [
        "div:has-text('Đang tìm kiếm')",
        "[data-testid='relationship-goal']"
    ],
    "profile_distance": [
        "div:has-text('Cách xa')",
        "[data-testid='profile-distance']"
    ],

    # Recs / Swiping Controls
    "swipe_like": [
        "button[aria-label*='Thích']",
        "button[aria-label*='Like']",
        "[data-testid='gamepad-like']"
    ],
    "swipe_pass": [
        "button[aria-label*='Không thích']",
        "button[aria-label*='Pass']",
        "button[aria-label*='Nope']",
        "[data-testid='gamepad-pass']"
    ],
    "out_of_likes_modal": [
        "div:has-text('Hết lượt thích')",
        "div:has-text('You are out of likes')",
        "div:has-text('Out of Likes')",
        "button:has-text('Mua thêm lượt Thích')",
        "button:has-text('Get Tinder Plus')",
        "button:has-text('Nhận Tinder Gold')"
    ],
    "popup_dismiss_buttons": [
        "button:has-text('Có lẽ để sau đi')",
        "button:has-text('Không quan tâm')",
        "button:has-text('Maybe later')",
        "button:has-text('Not interested')",
        "button:has-text('Không phải bây giờ')",
        "button:has-text('Not now')",
        "button:has-text('Bỏ qua')",
        "button:has-text('Tôi đồng ý')",
        "button:has-text('I accept')",
        "button:has-text('Tôi chấp nhận')"
    ]
}


def get_selector(key: str) -> list[str]:
    return TINDER_SELECTORS.get(key, [])
