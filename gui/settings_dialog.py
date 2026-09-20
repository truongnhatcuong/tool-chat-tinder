"""Settings dialog modal providing AI, automation, database, and safety controls."""
import asyncio
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTabWidget,
    QWidget,
    QLabel,
    QLineEdit,
    QSpinBox,
    QDoubleSpinBox,
    QCheckBox,
    QComboBox,
    QPushButton,
    QMessageBox
)
from config.settings import get_settings


class SettingsDialog(QDialog):
    """Configuration dialog with tabs for AI, Automation, Database, and Safety."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings - Tinder AI Assistant")
        self.resize(520, 480)
        self.setStyleSheet("""
            QDialog {
                background: #1E1E1E;
                color: #E0E0E0;
            }
            QLabel {
                color: #D0D0D0;
                font-size: 12px;
            }
            QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
                background: #2D2D2D;
                color: #FFFFFF;
                border: 1px solid #3E3E3E;
                border-radius: 4px;
                padding: 4px 8px;
            }
            QTabWidget::pane {
                border: 1px solid #333333;
                background: #252526;
            }
            QTabBar::tab {
                background: #2D2D2D;
                color: #CCCCCC;
                padding: 8px 16px;
                border: 1px solid #333;
                border-bottom: none;
            }
            QTabBar::tab:selected {
                background: #252526;
                color: #FFFFFF;
                font-weight: bold;
            }
        """)

        self.settings = get_settings()
        
        main_layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        self._build_ai_tab()
        self._build_automation_tab()
        self._build_database_tab()
        self._build_safety_tab()

        # Action Buttons
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        self.btn_save = QPushButton("Save Settings")
        self.btn_save.setStyleSheet("background: #0E639C; color: white; padding: 6px 16px; border-radius: 4px; font-weight: bold;")
        self.btn_save.clicked.connect(self._on_save)
        btn_layout.addWidget(self.btn_save)
        
        self.btn_cancel = QPushButton("Cancel")
        self.btn_cancel.setStyleSheet("background: #3A3D41; color: white; padding: 6px 14px; border-radius: 4px;")
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        
        main_layout.addLayout(btn_layout)

    def _build_ai_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("AI Base URL (OpenAI-compatible):"))
        self.txt_ai_base = QLineEdit(self.settings.ai_base_url)
        layout.addWidget(self.txt_ai_base)
        
        layout.addWidget(QLabel("AI API Key:"))
        self.txt_ai_key = QLineEdit(self.settings.ai_api_key)
        self.txt_ai_key.setEchoMode(QLineEdit.Password)
        layout.addWidget(self.txt_ai_key)
        
        layout.addWidget(QLabel("AI Model:"))
        self.txt_ai_model = QLineEdit(self.settings.ai_model)
        layout.addWidget(self.txt_ai_model)
        
        layout.addWidget(QLabel("Temperature (0.0 - 1.0):"))
        self.spin_temp = QDoubleSpinBox()
        self.spin_temp.setRange(0.0, 1.0)
        self.spin_temp.setSingleStep(0.05)
        self.spin_temp.setValue(self.settings.ai.temperature)
        layout.addWidget(self.spin_temp)
        
        layout.addWidget(QLabel("Max Tokens per Response:"))
        self.spin_tokens = QSpinBox()
        self.spin_tokens.setRange(20, 1000)
        self.spin_tokens.setValue(self.settings.ai.max_tokens)
        layout.addWidget(self.spin_tokens)
        
        layout.addStretch()
        self.tabs.addTab(tab, "AI Config")

    def _build_automation_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("Match Scan Interval (seconds):"))
        self.spin_match_interval = QDoubleSpinBox()
        self.spin_match_interval.setRange(2.0, 120.0)
        self.spin_match_interval.setValue(self.settings.scanner.match_scan_interval)
        layout.addWidget(self.spin_match_interval)
        
        layout.addWidget(QLabel("Message Scan Interval (seconds):"))
        self.spin_msg_interval = QDoubleSpinBox()
        self.spin_msg_interval.setRange(1.0, 30.0)
        self.spin_msg_interval.setValue(self.settings.scanner.message_scan_interval)
        layout.addWidget(self.spin_msg_interval)
        
        layout.addWidget(QLabel("Message Debounce (seconds):"))
        self.spin_debounce = QDoubleSpinBox()
        self.spin_debounce.setRange(1.0, 30.0)
        self.spin_debounce.setValue(self.settings.automation.message_debounce_seconds)
        layout.addWidget(self.spin_debounce)
        
        layout.addWidget(QLabel("Reply Delay Min / Max (seconds):"))
        delay_row = QHBoxLayout()
        self.spin_delay_min = QDoubleSpinBox()
        self.spin_delay_min.setRange(1.0, 60.0)
        self.spin_delay_min.setValue(self.settings.automation.reply_delay_min)
        delay_row.addWidget(self.spin_delay_min)
        
        self.spin_delay_max = QDoubleSpinBox()
        self.spin_delay_max.setRange(1.0, 60.0)
        self.spin_delay_max.setValue(self.settings.automation.reply_delay_max)
        delay_row.addWidget(self.spin_delay_max)
        layout.addLayout(delay_row)
        
        layout.addWidget(QLabel("Max Parallel Conversations:"))
        self.spin_parallel = QSpinBox()
        self.spin_parallel.setRange(1, 20)
        self.spin_parallel.setValue(self.settings.automation.max_parallel_conversations)
        layout.addWidget(self.spin_parallel)
        
        layout.addWidget(QLabel("Default Match Mode:"))
        self.combo_default_mode = QComboBox()
        self.combo_default_mode.addItems(["SUGGEST", "AUTO", "OFF"])
        self.combo_default_mode.setCurrentText(self.settings.automation.default_match_mode)
        layout.addWidget(self.combo_default_mode)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Automation")

    def _build_database_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        layout.addWidget(QLabel("Database Connection URL:"))
        lbl_hint = QLabel("(Supports MySQL: mysql+aiomysql://user:pass@host:port/dbname\nor SQLite: sqlite+aiosqlite:///./data/tinder_ai.db)")
        lbl_hint.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(lbl_hint)
        
        self.txt_db_url = QLineEdit(self.settings.database_url)
        layout.addWidget(self.txt_db_url)
        
        btn_test_db = QPushButton("Test Database Connection")
        btn_test_db.setStyleSheet("background: #2D2D2D; border: 1px solid #444; padding: 6px; border-radius: 4px;")
        btn_test_db.clicked.connect(self._test_database)
        layout.addWidget(btn_test_db)
        
        self.lbl_db_result = QLabel("")
        self.lbl_db_result.setStyleSheet("font-size: 11px;")
        layout.addWidget(self.lbl_db_result)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Database")

    def _build_safety_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        
        self.chk_dry_run = QCheckBox("Dry Run Mode (Simulate without sending real messages)")
        self.chk_dry_run.setChecked(self.settings.dry_run)
        layout.addWidget(self.chk_dry_run)
        
        self.chk_auto_reply = QCheckBox("Global Auto Reply Enabled")
        self.chk_auto_reply.setChecked(self.settings.global_auto_reply)
        layout.addWidget(self.chk_auto_reply)
        
        self.chk_inspect_dom = QCheckBox("DOM Inspection Mode")
        self.chk_inspect_dom.setChecked(self.settings.inspect_dom)
        layout.addWidget(self.chk_inspect_dom)
        
        lbl_warn = QLabel(
            "Note: Dry Run is enabled by default to prevent accidental message dispatch.\n"
            "Real sending is only possible when Dry Run is OFF and target match is in AUTO mode."
        )
        lbl_warn.setWordWrap(True)
        lbl_warn.setStyleSheet("color: #E5B567; margin-top: 10px; font-size: 11px;")
        layout.addWidget(lbl_warn)
        
        layout.addStretch()
        self.tabs.addTab(tab, "Safety")

    def _test_database(self):
        self.lbl_db_result.setText("Testing connection...")
        self.lbl_db_result.setStyleSheet("color: #E0E0E0;")
        # Simple test
        try:
            from database.db import test_db_connection
            # Run test
            loop = asyncio.get_event_loop()
            ok = loop.run_until_complete(test_db_connection())
            if ok:
                self.lbl_db_result.setText("✓ Connection successful!")
                self.lbl_db_result.setStyleSheet("color: #4EC9B0;")
            else:
                self.lbl_db_result.setText("✗ Connection failed. Check logs.")
                self.lbl_db_result.setStyleSheet("color: #F14C4C;")
        except Exception as e:
            self.lbl_db_result.setText(f"✗ Connection error: {e}")
            self.lbl_db_result.setStyleSheet("color: #F14C4C;")

    def _on_save(self):
        # Update settings instance
        self.settings.ai_base_url = self.txt_ai_base.text().strip()
        self.settings.ai_api_key = self.txt_ai_key.text().strip()
        self.settings.ai_model = self.txt_ai_model.text().strip()
        self.settings.ai.temperature = self.spin_temp.value()
        self.settings.ai.max_tokens = self.spin_tokens.value()
        
        self.settings.scanner.match_scan_interval = self.spin_match_interval.value()
        self.settings.scanner.message_scan_interval = self.spin_msg_interval.value()
        self.settings.automation.message_debounce_seconds = self.spin_debounce.value()
        self.settings.automation.reply_delay_min = self.spin_delay_min.value()
        self.settings.automation.reply_delay_max = self.spin_delay_max.value()
        self.settings.automation.max_parallel_conversations = self.spin_parallel.value()
        self.settings.automation.default_match_mode = self.combo_default_mode.currentText()
        
        self.settings.database_url = self.txt_db_url.text().strip()
        self.settings.dry_run = self.chk_dry_run.isChecked()
        self.settings.global_auto_reply = self.chk_auto_reply.isChecked()
        self.settings.inspect_dom = self.chk_inspect_dom.isChecked()
        
        # Persist JSON configs
        self.settings.save_config_json()
        
        QMessageBox.information(self, "Settings Saved", "Settings updated and saved successfully.")
        self.accept()
