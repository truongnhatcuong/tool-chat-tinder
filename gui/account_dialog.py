"""Account manager dialog modal for switching, adding, renaming, and deleting profiles."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QTableWidget,
    QTableWidgetItem,
    QPushButton,
    QLabel,
    QMessageBox,
    QInputDialog,
    QHeaderView
)
from services.account_service import AccountService
from utils.logger import logger


class AccountManagerDialog(QDialog):
    """Modal dialog for managing multi-account Tinder browser profiles."""
    account_switched = Signal(str)  # account_id
    account_created = Signal(str)   # account_id

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Quản lý tài khoản Tinder (Multi-Account)")
        self.resize(580, 360)
        self.setStyleSheet("""
            QDialog {
                background: #1E1E1E;
                color: #E0E0E0;
            }
            QLabel {
                color: #D0D0D0;
            }
            QTableWidget {
                background: #252526;
                color: #FFFFFF;
                border: 1px solid #333333;
                gridline-color: #2D2D2D;
                selection-background-color: #094771;
                font-size: 12px;
            }
            QHeaderView::section {
                background: #2D2D2D;
                color: #CCCCCC;
                padding: 4px;
                border: 1px solid #333333;
                font-weight: bold;
            }
            QPushButton {
                background: #2D2D2D;
                color: #E0E0E0;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 6px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: #3D3D3D;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        title = QLabel("Danh sách hồ sơ tài khoản Tinder:")
        title.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF;")
        layout.addWidget(title)

        # Table
        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["Tên tài khoản", "Trạng thái", "Thư mục lưu trữ"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        layout.addWidget(self.table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_switch = QPushButton("🔄 Chuyển sang nick này")
        self.btn_switch.setStyleSheet("background: #0E639C; color: white;")
        self.btn_switch.clicked.connect(self._on_switch_selected)
        btn_layout.addWidget(self.btn_switch)

        self.btn_add = QPushButton("➕ Thêm nick mới")
        self.btn_add.setStyleSheet("background: #196F3D; color: white;")
        self.btn_add.clicked.connect(self._on_add_account)
        btn_layout.addWidget(self.btn_add)

        self.btn_rename = QPushButton("✏️ Đổi tên")
        self.btn_rename.clicked.connect(self._on_rename_selected)
        btn_layout.addWidget(self.btn_rename)

        self.btn_delete = QPushButton("🗑️ Xóa")
        self.btn_delete.setStyleSheet("background: #A93226; color: white;")
        self.btn_delete.clicked.connect(self._on_delete_selected)
        btn_layout.addWidget(self.btn_delete)

        btn_layout.addStretch()

        btn_close = QPushButton("Đóng")
        btn_close.clicked.connect(self.close)
        btn_layout.addWidget(btn_close)

        layout.addLayout(btn_layout)

        self.refresh_table()

    def refresh_table(self):
        """Reload accounts from AccountService into table."""
        accounts = AccountService.get_accounts()
        active = AccountService.get_active_account()
        active_id = active.get("id")

        self.table.setRowCount(len(accounts))
        for row, acc in enumerate(accounts):
            acc_id = acc.get("id", "")
            is_active = (acc_id == active_id)

            item_name = QTableWidgetItem(acc.get("name", "Unknown"))
            item_name.setData(Qt.UserRole, acc_id)

            status_str = "🟢 Đang dùng" if is_active else "⚪ Sẵn sàng"
            item_status = QTableWidgetItem(status_str)
            item_status.setTextAlignment(Qt.AlignCenter)

            item_path = QTableWidgetItem(acc.get("profile_dir", ""))

            if is_active:
                item_name.setForeground(Qt.green)
                item_status.setForeground(Qt.green)

            self.table.setItem(row, 0, item_name)
            self.table.setItem(row, 1, item_status)
            self.table.setItem(row, 2, item_path)

    def _get_selected_account_id(self) -> str | None:
        selected_rows = self.table.selectedItems()
        if not selected_rows:
            return None
        item = self.table.item(self.table.currentRow(), 0)
        return item.data(Qt.UserRole) if item else None

    def _on_switch_selected(self):
        acc_id = self._get_selected_account_id()
        if not acc_id:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn 1 tài khoản trong danh sách.")
            return

        active = AccountService.get_active_account()
        if acc_id == active.get("id"):
            QMessageBox.information(self, "Thông báo", "Tài khoản này đang hoạt động rồi.")
            return

        self.account_switched.emit(acc_id)
        self.accept()

    def _on_add_account(self):
        name, ok = QInputDialog.getText(
            self,
            "Thêm tài khoản mới",
            "Nhập tên gợi nhớ cho tài khoản mới (ví dụ: Nick 2, Nick phụ, v.v.):"
        )
        if not ok or not name.strip():
            return

        clean_name = name.strip()
        new_acc = AccountService.add_account(clean_name)
        self.refresh_table()

        confirm = QMessageBox.question(
            self,
            "Chuyển tài khoản ngay?",
            f"Đã tạo hồ sơ '{clean_name}'.\n\nBạn có muốn chuyển sang tài khoản này ngay để đăng nhập không?",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            self.account_switched.emit(new_acc["id"])
            self.accept()

    def _on_rename_selected(self):
        acc_id = self._get_selected_account_id()
        if not acc_id:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn 1 tài khoản để đổi tên.")
            return

        acc = AccountService.get_account_by_id(acc_id)
        if not acc:
            return

        new_name, ok = QInputDialog.getText(
            self,
            "Đổi tên tài khoản",
            "Nhập tên mới cho tài khoản:",
            text=acc.get("name", "")
        )
        if ok and new_name.strip():
            AccountService.rename_account(acc_id, new_name.strip())
            self.refresh_table()

    def _on_delete_selected(self):
        acc_id = self._get_selected_account_id()
        if not acc_id:
            QMessageBox.information(self, "Thông báo", "Vui lòng chọn 1 tài khoản để xóa.")
            return

        accounts = AccountService.get_accounts()
        if len(accounts) <= 1:
            QMessageBox.warning(self, "Không thể xóa", "Không thể xóa tài khoản duy nhất còn lại!")
            return

        acc = AccountService.get_account_by_id(acc_id)
        confirm = QMessageBox.question(
            self,
            "Xác nhận xóa",
            f"Bạn có chắc muốn xóa hồ sơ '{acc.get('name', '')}'?\n(Dữ liệu cấu hình tài khoản sẽ bị xóa khỏi danh sách)",
            QMessageBox.Yes | QMessageBox.No
        )
        if confirm == QMessageBox.Yes:
            AccountService.delete_account(acc_id)
            self.refresh_table()
