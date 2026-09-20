"""Main desktop application window for Tinder AI Assistant."""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QSplitter,
    QLabel,
    QPushButton,
    QFrame,
    QStatusBar,
    QMessageBox,
    QComboBox,
    QInputDialog
)
from config.settings import get_settings
from gui.matches_panel import MatchesPanel
from gui.conversation_panel import ConversationPanel
from gui.reply_panel import ReplyPanel
from gui.settings_dialog import SettingsDialog
from gui.account_dialog import AccountManagerDialog
from services.account_service import AccountService
from utils.logger import logger, register_gui_log_callback


class MainWindow(QMainWindow):
    """Primary PySide6 Desktop GUI."""
    account_switch_requested = Signal(str)      # account_id
    account_login_requested = Signal()
    account_logout_requested = Signal()
    account_add_requested = Signal()

    def __init__(self):
        super().__init__()
        self.settings = get_settings()
        self.setWindowTitle("Tinder AI Assistant - Local Desktop Automation")
        self.resize(1100, 750)
        self.setStyleSheet("""
            QMainWindow {
                background: #121212;
            }
            QWidget {
                color: #E0E0E0;
                font-family: 'Segoe UI', Arial, sans-serif;
                font-size: 13px;
            }
            QSplitter::handle {
                background: #2D2D2D;
            }
        """)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        root_layout = QVBoxLayout(central_widget)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(8)

        # 1. Top Status Banner
        self._build_header(root_layout)

        # 2. Main Work Area (Splitter: Matches | Conversation & Replies)
        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(2)
        
        self.matches_panel = MatchesPanel()
        splitter.addWidget(self.matches_panel)
        splitter.setStretchFactor(0, 1)

        right_container = QWidget()
        right_layout = QVBoxLayout(right_container)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(6)

        self.conversation_panel = ConversationPanel()
        right_layout.addWidget(self.conversation_panel, stretch=3)

        self.reply_panel = ReplyPanel()
        right_layout.addWidget(self.reply_panel, stretch=1)

        splitter.addWidget(right_container)
        splitter.setStretchFactor(1, 2)
        root_layout.addWidget(splitter)

        # 3. Bottom Emergency Controls & Action Bar
        self._build_bottom_controls(root_layout)

        # Status Bar
        self.status_bar = QStatusBar()
        self.status_bar.setStyleSheet("background: #181818; color: #888888; font-size: 11px;")
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("Ready. System running in safe DRY RUN mode.")

        # Connect internal signals
        self._connect_signals()

        # Connect logger to status bar
        register_gui_log_callback(self._on_log_message)

        # Populate accounts list
        self.refresh_accounts()

    def _build_header(self, parent_layout: QVBoxLayout):
        header_frame = QFrame()
        header_frame.setStyleSheet("""
            QFrame {
                background: #1E1E1E;
                border: 1px solid #2D2D2D;
                border-radius: 6px;
                padding: 4px 8px;
            }
        """)
        h_layout = QHBoxLayout(header_frame)
        h_layout.setContentsMargins(8, 6, 8, 6)
        h_layout.setSpacing(10)

        # Indicators
        self.lbl_tinder_status = QLabel("Tinder: ● Disconnected")
        self.lbl_tinder_status.setStyleSheet("color: #FF6B6B; font-weight: bold; font-size: 12px;")
        h_layout.addWidget(self.lbl_tinder_status)

        self.lbl_ai_status = QLabel("AI: ● Initializing")
        self.lbl_ai_status.setStyleSheet("color: #E5B567; font-weight: bold; font-size: 12px;")
        h_layout.addWidget(self.lbl_ai_status)

        self.lbl_dom_status = QLabel("DOM: ● Pending")
        self.lbl_dom_status.setStyleSheet("color: #AAAAAA; font-weight: bold; font-size: 12px;")
        h_layout.addWidget(self.lbl_dom_status)

        h_layout.addSpacing(10)

        self.lbl_dry_run = QLabel(f"Dry Run: {'ON' if self.settings.dry_run else 'OFF'}")
        self.lbl_dry_run.setStyleSheet("color: #4EC9B0; font-weight: bold;")
        h_layout.addWidget(self.lbl_dry_run)

        self.lbl_auto_reply = QLabel(f"Auto Reply: {'ON' if self.settings.global_auto_reply else 'OFF'}")
        self.lbl_auto_reply.setStyleSheet("color: #888888; font-weight: bold;")
        h_layout.addWidget(self.lbl_auto_reply)

        h_layout.addStretch()

        # Account Management Toolbar
        acc_frame = QFrame()
        acc_frame.setStyleSheet("""
            QFrame {
                background: #252526;
                border: 1px solid #383838;
                border-radius: 4px;
                padding: 1px 4px;
            }
        """)
        acc_layout = QHBoxLayout(acc_frame)
        acc_layout.setContentsMargins(4, 2, 4, 2)
        acc_layout.setSpacing(6)

        lbl_acc_icon = QLabel("👤")
        lbl_acc_icon.setStyleSheet("font-size: 13px;")
        acc_layout.addWidget(lbl_acc_icon)

        self.combo_accounts = QComboBox()
        self.combo_accounts.setStyleSheet("""
            QComboBox {
                background: #1E1E1E;
                color: #FFFFFF;
                border: 1px solid #4A4A4A;
                border-radius: 3px;
                padding: 3px 8px;
                font-weight: bold;
                font-size: 12px;
                min-width: 140px;
            }
            QComboBox::drop-down { border: none; }
            QComboBox QAbstractItemView {
                background: #1E1E1E;
                color: #FFFFFF;
                selection-background-color: #094771;
            }
        """)
        self.combo_accounts.currentIndexChanged.connect(self._on_account_combo_changed)
        acc_layout.addWidget(self.combo_accounts)

        self.btn_login = QPushButton("🔑 Đăng nhập")
        self.btn_login.setToolTip("Mở trình duyệt Tinder để đăng nhập")
        self.btn_login.setStyleSheet("""
            QPushButton {
                background: #1B4F72;
                color: white;
                font-weight: bold;
                border-radius: 3px;
                padding: 4px 10px;
                border: 1px solid #2980B9;
                font-size: 12px;
            }
            QPushButton:hover { background: #2980B9; }
        """)
        self.btn_login.clicked.connect(self.account_login_requested.emit)
        acc_layout.addWidget(self.btn_login)

        self.btn_logout = QPushButton("🚪 Đăng xuất")
        self.btn_logout.setToolTip("Đăng xuất khỏi tài khoản Tinder hiện tại")
        self.btn_logout.setStyleSheet("""
            QPushButton {
                background: #4A235A;
                color: #E8DAEF;
                font-weight: bold;
                border-radius: 3px;
                padding: 4px 10px;
                border: 1px solid #7D3C98;
                font-size: 12px;
            }
            QPushButton:hover { background: #6C3483; color: white; }
        """)
        self.btn_logout.clicked.connect(self.account_logout_requested.emit)
        acc_layout.addWidget(self.btn_logout)

        self.btn_add_account = QPushButton("➕ Thêm nick")
        self.btn_add_account.setToolTip("Tạo hồ sơ trình duyệt cho tài khoản Tinder mới")
        self.btn_add_account.setStyleSheet("""
            QPushButton {
                background: #145A32;
                color: #D4EFDF;
                font-weight: bold;
                border-radius: 3px;
                padding: 4px 10px;
                border: 1px solid #27AE60;
                font-size: 12px;
            }
            QPushButton:hover { background: #1E8449; color: white; }
        """)
        self.btn_add_account.clicked.connect(self.account_add_requested.emit)
        acc_layout.addWidget(self.btn_add_account)

        self.btn_manage_accounts = QPushButton("⚙ Quản lý nick")
        self.btn_manage_accounts.setToolTip("Xem danh sách, đổi tên hoặc xóa hồ sơ tài khoản")
        self.btn_manage_accounts.setStyleSheet("""
            QPushButton {
                background: #2C3E50;
                color: #BDC3C7;
                border-radius: 3px;
                padding: 4px 8px;
                border: 1px solid #415B76;
                font-size: 12px;
            }
            QPushButton:hover { background: #34495E; color: white; }
        """)
        self.btn_manage_accounts.clicked.connect(self._open_account_manager)
        acc_layout.addWidget(self.btn_manage_accounts)

        h_layout.addWidget(acc_frame)

        btn_settings = QPushButton("⚙ Settings")
        btn_settings.setStyleSheet("""
            QPushButton {
                background: #2D2D2D;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 4px 12px;
                color: #E0E0E0;
            }
            QPushButton:hover { background: #3D3D3D; }
        """)
        btn_settings.clicked.connect(self._open_settings)
        h_layout.addWidget(btn_settings)

        parent_layout.addWidget(header_frame)

    def _build_bottom_controls(self, parent_layout: QVBoxLayout):
        bottom_frame = QFrame()
        bottom_frame.setStyleSheet("""
            QFrame {
                background: #181818;
                border-top: 1px solid #282828;
                padding: 4px;
            }
        """)
        b_layout = QHBoxLayout(bottom_frame)
        b_layout.setContentsMargins(4, 4, 4, 4)

        self.btn_pause = QPushButton("⏸ PAUSE ALL")
        self.btn_pause.setStyleSheet("""
            QPushButton {
                background: #8A6D3B;
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #A07D42; }
        """)
        self.btn_pause.clicked.connect(self._toggle_pause)
        b_layout.addWidget(self.btn_pause)

        self.btn_stop = QPushButton("🛑 STOP AUTOMATION (Emergency)")
        self.btn_stop.setStyleSheet("""
            QPushButton {
                background: #A93226;
                color: white;
                font-weight: bold;
                padding: 8px 18px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #C0392B; }
        """)
        self.btn_stop.clicked.connect(self._emergency_stop)
        self.btn_auto_swipe = QPushButton("⚡ Auto-Like (Hết lượt)")
        self.btn_auto_swipe.setStyleSheet("""
            QPushButton {
                background: #196F3D;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #229954; }
        """)
        b_layout.addWidget(self.btn_auto_swipe)

        self.btn_auto_opener = QPushButton("💌 Auto-Opener (Thả thính)")
        self.btn_auto_opener.setStyleSheet("""
            QPushButton {
                background: #7D3C98;
                color: white;
                font-weight: bold;
                padding: 8px 16px;
                border: none;
                border-radius: 4px;
            }
            QPushButton:hover { background: #8E44AD; }
        """)
        b_layout.addWidget(self.btn_auto_opener)

        b_layout.addStretch()

        self.lbl_last_action = QLabel("Engine idle.")
        self.lbl_last_action.setStyleSheet("color: #777777; font-size: 11px;")
        b_layout.addWidget(self.lbl_last_action)

        parent_layout.addWidget(bottom_frame)

    def _connect_signals(self):
        self.matches_panel.match_selected.connect(self._on_match_selected)
        self.matches_panel.match_mode_updated.connect(self._on_match_mode_updated)
        self.reply_panel.send_requested.connect(self._on_send_requested)
        self.reply_panel.regenerate_requested.connect(self._on_regenerate_requested)
        self.reply_panel.reject_requested.connect(self._on_reject_requested)

    def _open_settings(self):
        dialog = SettingsDialog(self)
        if dialog.exec():
            # Refresh header badges
            self.lbl_dry_run.setText(f"Dry Run: {'ON' if self.settings.dry_run else 'OFF'}")
            self.lbl_auto_reply.setText(f"Auto Reply: {'ON' if self.settings.global_auto_reply else 'OFF'}")

    def _toggle_pause(self):
        self.settings.is_paused = not self.settings.is_paused
        if self.settings.is_paused:
            self.btn_pause.setText("▶ RESUME")
            self.btn_pause.setStyleSheet("background: #2E7D32; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px;")
            self.status_bar.showMessage("ALL AUTOMATIONS PAUSED. Scanning continues, sending disabled.")
            logger.warning("Global pause activated by user.")
        else:
            self.btn_pause.setText("⏸ PAUSE ALL")
            self.btn_pause.setStyleSheet("background: #8A6D3B; color: white; font-weight: bold; padding: 8px 18px; border-radius: 4px;")
            self.status_bar.showMessage("Automations resumed.")
            logger.info("Global pause deactivated.")

    def _emergency_stop(self):
        self.settings.emergency_stop = True
        self.settings.global_auto_reply = False
        self.lbl_auto_reply.setText("Auto Reply: OFF")
        self.status_bar.showMessage("EMERGENCY STOP TRIGGERED. All workers and tasks cancelled.")
        logger.critical("EMERGENCY STOP CLICKED! Disabling auto-reply and stopping tasks.")
        QMessageBox.warning(
            self,
            "Emergency Stop",
            "Emergency Stop activated!\n\nAll sending tasks cancelled and Global Auto Reply disabled."
        )

    def _on_match_selected(self, tinder_id: str):
        logger.info(f"Match selected: {tinder_id}")
        self.status_bar.showMessage(f"Selected match: {tinder_id}")

    def _on_match_mode_updated(self, tinder_id: str, new_mode: str):
        logger.info(f"Updated mode for {tinder_id} -> {new_mode}")
        self.status_bar.showMessage(f"Match {tinder_id} mode set to {new_mode}")

    def _on_send_requested(self, conv_id: str, text: str):
        logger.info(f"Send requested for {conv_id}: {text[:30]}...")

    def _on_regenerate_requested(self, conv_id: str):
        logger.info(f"Regenerate requested for {conv_id}")

    def _on_reject_requested(self, conv_id: str):
        logger.info(f"Suggestion rejected for {conv_id}")

    def _on_log_message(self, msg: str):
        # Update short status
        short_msg = msg.split("] ", 2)[-1] if "] " in msg else msg
        self.lbl_last_action.setText(short_msg[:80])

    def set_tinder_status(self, connected: bool, message: str = ""):
        if connected:
            self.lbl_tinder_status.setText("Tinder: ● Connected")
            self.lbl_tinder_status.setStyleSheet("color: #4EC9B0; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_tinder_status.setText(f"Tinder: ● {message or 'Disconnected'}")
            self.lbl_tinder_status.setStyleSheet("color: #FF6B6B; font-weight: bold; font-size: 12px;")

    def set_ai_status(self, connected: bool, message: str = ""):
        if connected:
            self.lbl_ai_status.setText("AI: ● Ready")
            self.lbl_ai_status.setStyleSheet("color: #4EC9B0; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_ai_status.setText(f"AI: ● {message or 'Disconnected'}")
            self.lbl_ai_status.setStyleSheet("color: #E5B567; font-weight: bold; font-size: 12px;")

    def set_dom_status(self, healthy: bool, message: str = ""):
        if healthy:
            self.lbl_dom_status.setText("DOM: ● Healthy")
            self.lbl_dom_status.setStyleSheet("color: #4EC9B0; font-weight: bold; font-size: 12px;")
        else:
            self.lbl_dom_status.setText(f"DOM: ● {message or 'Check Failed'}")
            self.lbl_dom_status.setStyleSheet("color: #FF6B6B; font-weight: bold; font-size: 12px;")

    def refresh_accounts(self):
        """Populate account dropdown with registered profiles."""
        self.combo_accounts.blockSignals(True)
        self.combo_accounts.clear()
        accounts = AccountService.get_accounts()
        active = AccountService.get_active_account()
        active_id = active.get("id")
        selected_index = 0

        for i, acc in enumerate(accounts):
            acc_id = acc.get("id", "")
            self.combo_accounts.addItem(f"👤 {acc.get('name', 'Tài khoản')}", acc_id)
            if acc_id == active_id:
                selected_index = i

        self.combo_accounts.setCurrentIndex(selected_index)
        self.combo_accounts.blockSignals(False)

    def _on_account_combo_changed(self, index: int):
        if index >= 0:
            acc_id = self.combo_accounts.itemData(index)
            if acc_id:
                self.account_switch_requested.emit(acc_id)

    def _open_account_manager(self):
        dialog = AccountManagerDialog(self)
        dialog.account_switched.connect(lambda acc_id: self.account_switch_requested.emit(acc_id))
        dialog.exec()
        self.refresh_accounts()
