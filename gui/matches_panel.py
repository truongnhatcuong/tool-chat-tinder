"""Matches list panel displaying matches, their statuses, and per-match modes."""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QComboBox
)

from config.settings import get_settings
class MatchListItemWidget(QWidget):
    """Custom widget for an item in the match list."""
    mode_changed = Signal(str, str)  # tinder_id, new_mode

    def __init__(self, tinder_id: str, name: str, status: str, mode: str, parent=None):
        super().__init__(parent)
        self.tinder_id = tinder_id
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        
        # Indicator dot and name
        self.lbl_name = QLabel(f"● {name}")
        self.lbl_name.setStyleSheet("font-weight: bold; font-size: 13px; color: #E0E0E0;")
        layout.addWidget(self.lbl_name)
        
        # Status
        self.lbl_status = QLabel(status)
        self.lbl_status.setStyleSheet("color: #888888; font-size: 11px;")
        layout.addWidget(self.lbl_status)
        layout.addStretch()
        
        # Mode selector combo
        self.combo_mode = QComboBox()
        self.combo_mode.addItems(["AUTO", "SUGGEST", "OFF"])
        self.combo_mode.setCurrentText(mode.upper() if mode else "OFF")
        self.combo_mode.setStyleSheet("""
            QComboBox {
                background: #2D2D2D;
                color: #FFFFFF;
                border: 1px solid #444;
                border-radius: 4px;
                padding: 2px 6px;
                font-size: 11px;
            }
        """)
        self.combo_mode.currentTextChanged.connect(self._on_mode_changed)
        layout.addWidget(self.combo_mode)

    def _on_mode_changed(self, new_mode: str):
        self.mode_changed.emit(self.tinder_id, new_mode)

    def set_mode(self, mode: str, block_signal: bool = False):
        """Update dropdown selection programmatically."""
        if block_signal:
            self.combo_mode.blockSignals(True)
        self.combo_mode.setCurrentText(mode.upper() if mode else "OFF")
        if block_signal:
            self.combo_mode.blockSignals(False)

    def update_status(self, status: str):
        self.lbl_status.setText(status)


class MatchesPanel(QWidget):
    """Panel holding matches with independent per-person mode controls."""
    match_selected = Signal(str)  # tinder_id
    match_mode_updated = Signal(str, str)  # tinder_id, new_mode

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        
        header = QLabel("Matches & Conversations")
        header.setStyleSheet("font-weight: bold; font-size: 14px; color: #FFFFFF; padding: 4px 6px;")
        layout.addWidget(header)

        hint = QLabel("Chỉ người được chọn AUTO mới được tự động nhắn")
        hint.setStyleSheet("color: #888888; font-size: 11px; padding: 0 6px 4px 6px;")
        layout.addWidget(hint)

        bulk_row = QHBoxLayout()
        bulk_row.setContentsMargins(6, 0, 6, 4)
        self.btn_all_auto = QPushButton("⚡ AUTO tất cả")
        self.btn_all_auto.setToolTip("Chuyển tất cả match sang AUTO")
        self.btn_all_auto.setStyleSheet(
            "QPushButton { background: #196F3D; color: white; font-weight: bold; border: none;"
            " border-radius: 4px; padding: 5px 10px; } QPushButton:hover { background: #229954; }"
        )
        self.btn_all_auto.clicked.connect(lambda: self.set_all_modes("AUTO"))
        bulk_row.addWidget(self.btn_all_auto)

        self.btn_all_off = QPushButton("⛔ OFF tất cả")
        self.btn_all_off.setToolTip("Tắt tự động cho tất cả match")
        self.btn_all_off.setStyleSheet(
            "QPushButton { background: #A93226; color: white; font-weight: bold; border: none;"
            " border-radius: 4px; padding: 5px 10px; } QPushButton:hover { background: #C0392B; }"
        )
        self.btn_all_off.clicked.connect(lambda: self.set_all_modes("OFF"))
        bulk_row.addWidget(self.btn_all_off)
        layout.addLayout(bulk_row)

        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet("""
            QListWidget {
                background: #1E1E1E;
                border: 1px solid #333333;
                border-radius: 6px;
            }
            QListWidget::item:selected {
                background: #2A3B4C;
            }
        """)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget)
        
        self._items_map: dict[str, tuple[QListWidgetItem, MatchListItemWidget]] = {}

    def set_matches(self, matches_data: list[dict]):
        self.list_widget.clear()
        self._items_map.clear()
        for item in matches_data:
            self.add_or_update_match(
                tinder_id=item["tinder_id"],
                name=item["name"],
                status=item.get("status", "Idle"),
                mode=item.get("mode", get_settings().automation.default_match_mode)
            )

    def add_or_update_match(self, tinder_id: str, name: str, status: str, mode: str):
        if tinder_id in self._items_map:
            _, widget = self._items_map[tinder_id]
            widget.update_status(status)
            return

        list_item = QListWidgetItem(self.list_widget)
        widget = MatchListItemWidget(tinder_id, name, status, mode)
        widget.mode_changed.connect(self.match_mode_updated.emit)
        
        list_item.setSizeHint(widget.sizeHint())
        list_item.setData(Qt.UserRole, tinder_id)
        self.list_widget.addItem(list_item)
        self.list_widget.setItemWidget(list_item, widget)
        self._items_map[tinder_id] = (list_item, widget)

    def set_all_modes(self, mode: str):
        """Set every match to `mode`; unchanged ones emit nothing, changed ones go through the normal mode signal."""
        for _, widget in self._items_map.values():
            widget.set_mode(mode)

    def update_match_mode(self, tinder_id: str, new_mode: str):
        """Update a specific match's mode programmatically."""
        if tinder_id in self._items_map:
            _, widget = self._items_map[tinder_id]
            widget.set_mode(new_mode, block_signal=True)

    def update_match_status(self, tinder_id: str, status: str):
        """Update a specific match's status display."""
        if tinder_id in self._items_map:
            _, widget = self._items_map[tinder_id]
            widget.update_status(status)

    def remove_match(self, tinder_id: str):
        """Remove match from UI list widget when unmatched."""
        if tinder_id in self._items_map:
            item, _ = self._items_map.pop(tinder_id)
            row = self.list_widget.row(item)
            if row >= 0:
                self.list_widget.takeItem(row)

    def clear_matches(self):
        """Clear all matches from UI list widget."""
        self.list_widget.clear()
        self._items_map.clear()

    def _on_item_clicked(self, item: QListWidgetItem):
        tinder_id = item.data(Qt.UserRole)
        if tinder_id:
            self.match_selected.emit(tinder_id)
