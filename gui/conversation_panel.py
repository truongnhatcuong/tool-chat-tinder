"""Conversation panel displaying profile details and chat history."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextBrowser,
    QFrame
)


class ConversationPanel(QWidget):
    """Panel displaying match profile summary and conversation transcript."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        
        # Profile header card
        self.profile_frame = QFrame()
        self.profile_frame.setStyleSheet("""
            QFrame {
                background: #252526;
                border: 1px solid #333333;
                border-radius: 6px;
                padding: 8px;
            }
        """)
        pf_layout = QVBoxLayout(self.profile_frame)
        pf_layout.setContentsMargins(6, 6, 6, 6)
        
        self.lbl_profile_name = QLabel("No match selected")
        self.lbl_profile_name.setStyleSheet("font-size: 15px; font-weight: bold; color: #FFFFFF;")
        pf_layout.addWidget(self.lbl_profile_name)
        
        self.lbl_profile_bio = QLabel("Select a match from the list to view profile and conversation.")
        self.lbl_profile_bio.setWordWrap(True)
        self.lbl_profile_bio.setStyleSheet("font-size: 12px; color: #CCCCCC;")
        pf_layout.addWidget(self.lbl_profile_bio)
        
        self.lbl_profile_interests = QLabel("")
        self.lbl_profile_interests.setStyleSheet("font-size: 11px; color: #3794FF;")
        pf_layout.addWidget(self.lbl_profile_interests)
        
        layout.addWidget(self.profile_frame)
        
        # Chat history view
        lbl_chat = QLabel("Conversation History:")
        lbl_chat.setStyleSheet("font-weight: bold; color: #AAAAAA; margin-top: 6px;")
        layout.addWidget(lbl_chat)
        
        self.chat_browser = QTextBrowser()
        self.chat_browser.setStyleSheet("""
            QTextBrowser {
                background: #181818;
                border: 1px solid #333333;
                border-radius: 6px;
                color: #E0E0E0;
                font-family: 'Segoe UI', Tahoma, sans-serif;
                font-size: 13px;
                padding: 10px;
            }
        """)
        layout.addWidget(self.chat_browser)

    def display_profile(self, name: str, age: int | None, bio: str | None, interests: list[str] | str | None):
        age_str = f" - {age}" if age else ""
        self.lbl_profile_name.setText(f"Selected: {name}{age_str}")
        self.lbl_profile_bio.setText(f"Bio: {bio or 'No bio provided'}")
        
        if isinstance(interests, list):
            interests_text = " / ".join(interests)
        elif isinstance(interests, str):
            interests_text = interests
        else:
            interests_text = "None"
        self.lbl_profile_interests.setText(f"Interests: {interests_text}")

    def display_messages(self, messages: list[dict]):
        html_lines = []
        for msg in messages:
            sender = msg.get("sender", "Unknown")
            role = msg.get("role", "incoming")
            content = msg.get("content", "")
            
            if role == "incoming":
                html_lines.append(
                    f"<div style='margin-bottom: 8px;'>"
                    f"<span style='color: #4EC9B0; font-weight: bold;'>{sender}:</span> "
                    f"<span style='color: #FFFFFF;'>{content}</span>"
                    f"</div>"
                )
            else:
                html_lines.append(
                    f"<div style='margin-bottom: 8px; text-align: right;'>"
                    f"<span style='color: #9CDCFE;'>{content}</span> "
                    f"<span style='color: #569CD6; font-weight: bold;'>:You</span>"
                    f"</div>"
                )
        self.chat_browser.setHtml("".join(html_lines))
        self.chat_browser.verticalScrollBar().setValue(
            self.chat_browser.verticalScrollBar().maximum()
        )

    def clear_conversation(self):
        """Reset conversation profile and chat history display."""
        self.lbl_profile_name.setText("No match selected")
        self.lbl_profile_bio.setText("Select a match from the list to view profile and conversation.")
        self.lbl_profile_interests.setText("")
        self.chat_browser.clear()
