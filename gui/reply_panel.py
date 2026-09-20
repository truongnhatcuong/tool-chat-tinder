"""Reply panel providing AI suggestion review, editing, regeneration, and sending."""
from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QTextEdit,
    QPushButton,
    QFrame
)


class ReplyPanel(QWidget):
    """Panel containing the AI generated response editor and action buttons."""
    send_requested = Signal(str, str)         # conversation_id, text
    regenerate_requested = Signal(str)       # conversation_id
    reject_requested = Signal(str)           # conversation_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_conversation_id: str | None = None
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        
        # Header / Status
        top_layout = QHBoxLayout()
        self.lbl_title = QLabel("AI Suggestion:")
        self.lbl_title.setStyleSheet("font-weight: bold; color: #DCDCDC; font-size: 13px;")
        top_layout.addWidget(self.lbl_title)
        
        self.lbl_status = QLabel("Idle")
        self.lbl_status.setStyleSheet("color: #888888; font-size: 11px;")
        top_layout.addWidget(self.lbl_status)
        top_layout.addStretch()
        layout.addLayout(top_layout)
        
        # Editable text box
        self.txt_suggestion = QTextEdit()
        self.txt_suggestion.setPlaceholderText("AI suggestion will appear here. You can edit the text before sending...")
        self.txt_suggestion.setStyleSheet("""
            QTextEdit {
                background: #252526;
                color: #FFFFFF;
                border: 1px solid #3C3C3C;
                border-radius: 6px;
                font-size: 13px;
                padding: 8px;
            }
        """)
        self.txt_suggestion.setMaximumHeight(90)
        layout.addWidget(self.txt_suggestion)
        
        # Action Buttons
        btn_layout = QHBoxLayout()
        
        self.btn_send = QPushButton("Send Reply")
        self.btn_send.setStyleSheet("""
            QPushButton {
                background: #0E639C;
                color: white;
                border: none;
                border-radius: 4px;
                font-weight: bold;
                padding: 6px 14px;
            }
            QPushButton:hover { background: #1177BB; }
            QPushButton:disabled { background: #444444; color: #777777; }
        """)
        self.btn_send.clicked.connect(self._on_send)
        btn_layout.addWidget(self.btn_send)
        
        self.btn_regenerate = QPushButton("Regenerate")
        self.btn_regenerate.setStyleSheet("""
            QPushButton {
                background: #3A3D41;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover { background: #4D5054; }
        """)
        self.btn_regenerate.clicked.connect(self._on_regenerate)
        btn_layout.addWidget(self.btn_regenerate)
        
        self.btn_reject = QPushButton("Reject")
        self.btn_reject.setStyleSheet("""
            QPushButton {
                background: #5A1D1D;
                color: #FFB3B3;
                border: none;
                border-radius: 4px;
                padding: 6px 12px;
            }
            QPushButton:hover { background: #7A2424; }
        """)
        self.btn_reject.clicked.connect(self._on_reject)
        btn_layout.addWidget(self.btn_reject)
        
        btn_layout.addStretch()
        layout.addLayout(btn_layout)

    def set_suggestion(self, conversation_id: str, suggestion_text: str, status: str = "Ready"):
        self.current_conversation_id = conversation_id
        self.txt_suggestion.setPlainText(suggestion_text)
        self.lbl_status.setText(status)
        self.btn_send.setEnabled(bool(suggestion_text.strip()))

    def clear(self):
        self.current_conversation_id = None
        self.txt_suggestion.clear()
        self.lbl_status.setText("Idle")
        self.btn_send.setEnabled(False)

    def clear_suggestion(self):
        """Alias for clear()."""
        self.clear()

    def _on_send(self):
        if self.current_conversation_id:
            text = self.txt_suggestion.toPlainText().strip()
            if text:
                self.send_requested.emit(self.current_conversation_id, text)

    def _on_regenerate(self):
        if self.current_conversation_id:
            self.regenerate_requested.emit(self.current_conversation_id)

    def _on_reject(self):
        if self.current_conversation_id:
            self.reject_requested.emit(self.current_conversation_id)
            self.clear()
