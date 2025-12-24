from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from core.backup import create_backup
from core.config_manager import ConfigManager, ensure_paths
from core.csv_storage import read_items, read_money, write_items, write_money
from core.models import DATE_FMT, ItemRecord, MoneyRecord
from scoring.scoring import ScoreResult, score_item


def _section_label(text: str) -> QtWidgets.QLabel:
    label = QtWidgets.QLabel(text)
    label.setObjectName("SectionTitle")
    return label


def _build_style_sheet(theme: dict) -> str:
    accent = theme.get("accent", "#2563eb")
    accent_hover = "#1d4ed8"
    muted = theme.get("muted", "#94a3b8")
    background = theme.get("background", "#f7f9fb")
    foreground = theme.get("foreground", "#0f172a")
    table = theme.get("table", {}) or {}
    header_bg = table.get("header_bg", "#e2e8f0")
    header_fg = table.get("header_fg", foreground)
    row_bg = table.get("row_bg", "#ffffff")
    alt_row_bg = table.get("alt_row_bg", "#f1f5f9")
    return f"""
    QWidget {{
        background-color: {background};
        color: {foreground};
        font: 14px "Segoe UI", "Inter", sans-serif;
    }}
    QTabWidget::pane {{
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        padding: 8px;
        margin-top: 6px;
    }}
    QTabBar::tab {{
        background: transparent;
        padding: 10px 16px;
        border: none;
        border-bottom: 2px solid transparent;
        margin-right: 6px;
        font-weight: 600;
    }}
    QTabBar::tab:selected {{
        color: {accent};
        border-bottom: 2px solid {accent};
    }}
    QLabel#SectionTitle {{
        font-weight: 700;
        letter-spacing: 0.5px;
        text-transform: uppercase;
        color: {muted};
        padding: 2px 0 4px;
    }}
    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {{
        background: #ffffff;
        border: 1px solid #d7dde5;
        border-radius: 8px;
        padding: 8px 10px;
        min-height: 32px;
    }}
    QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus {{
        border-color: {accent};
        outline: none;
    }}
    QComboBox QAbstractItemView {{
        selection-background-color: {accent};
        selection-color: #ffffff;
        padding: 6px;
    }}
    QPushButton {{
        background-color: {accent};
        color: #ffffff;
        border: 1px solid {accent};
        border-radius: 10px;
        padding: 8px 14px;
        font-weight: 600;
    }}
    QPushButton:hover {{
        background-color: {accent_hover};
        border-color: {accent_hover};
    }}
    QPushButton:disabled {{
        background: #e5e7eb;
        border-color: #e5e7eb;
        color: #9ca3af;
    }}
    QTableWidget {{
        border: 1px solid #e2e8f0;
        border-radius: 12px;
        gridline-color: #e2e8f0;
        background: {row_bg};
        alternate-background-color: {alt_row_bg};
        selection-background-color: {accent};
        selection-color: #ffffff;
    }}
    QTableWidget::item {{
        padding: 10px 12px;
    }}
    QTableWidget::item:selected {{
        background-color: {accent};
        color: #ffffff;
    }}
    QHeaderView::section {{
        background: {header_bg};
        color: {header_fg};
        padding: 10px 14px;
        border: none;
        border-bottom: 1px solid #d7dde5;
    }}
    QScrollBar:vertical {{
        width: 12px;
        background: transparent;
    }}
    QScrollBar::handle:vertical {{
        background: #cbd5e1;
        border-radius: 6px;
    }}
    QScrollBar::handle:vertical:hover {{
        background: #94a3b8;
    }}
    """


def launch() -> None:
    _detach_console_on_windows()
    app = QtWidgets.QApplication(sys.argv)
    config = ConfigManager()
    ensure_paths(config.settings)
    theme = config.get_theme()
    app.setStyleSheet(_build_style_sheet(theme))
    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self, config: ConfigManager) -> None:
        super().__init__()
        self.setWindowTitle("Finance Planner (Qt)")
        self.config_manager = config
        self.settings = config.settings
        self.weights = config.weights
        self.theme = config.get_theme()
        self.items_path = self.settings["paths"]["items_csv"]
        self.money_path = self.settings["paths"]["money_csv"]
        self.backup_dir = self.settings["paths"]["backup_dir"]
        self.date_fmt = self.settings["ui"]["date_format"]
        self.currency_symbol = self.settings["ui"]["currency_symbol"]

        self.items: List[ItemRecord] = []
        self.money: List[MoneyRecord] = []

        self.tabs = QtWidgets.QTabWidget()
        self.purchases_tab = PurchasesWidget(self)
        self.money_tab = MoneyWidget(self)
        self.settings_tab = SettingsWidget(self)
        self.tabs.addTab(self.purchases_tab, "Purchases")
        self.tabs.addTab(self.money_tab, "Money")
        self.tabs.addTab(self.settings_tab, "Settings")
        container = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(container)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(16)
        layout.addWidget(self.tabs)
        self.setCentralWidget(container)

        self._load_data()
        self._setup_shortcuts()

    def _setup_shortcuts(self) -> None:
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+F"), self, self._focus_search)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+N"), self, self._add_current)
        QtGui.QShortcut(QtGui.QKeySequence("Ctrl+E"), self, self._edit_current)

    def _focus_search(self) -> None:
        current = self.tabs.currentWidget()
        if isinstance(current, PurchasesWidget):
            current.search_edit.setFocus()
        elif isinstance(current, MoneyWidget):
            current.search_edit.setFocus()

    def _add_current(self) -> None:
        current = self.tabs.currentWidget()
        if isinstance(current, PurchasesWidget):
            current.add_item()
        elif isinstance(current, MoneyWidget):
            current.add_entry()

    def _edit_current(self) -> None:
        current = self.tabs.currentWidget()
        if isinstance(current, PurchasesWidget):
            current.edit_item()
        elif isinstance(current, MoneyWidget):
            current.edit_entry()

    def _load_data(self) -> None:
        self.items = read_items(self.items_path)
        self.money = read_money(self.money_path)
        self._sort_items()
        self._sort_money()
        self.purchases_tab.refresh()
        self.money_tab.refresh()

    def _sort_items(self) -> None:
        self.items.sort(key=lambda i: i.date, reverse=True)

    def _sort_money(self) -> None:
        self.money.sort(key=lambda m: m.date, reverse=True)

    def save_items(self, trigger_backup: bool = True) -> None:
        write_items(self.items_path, self.items)
        if trigger_backup:
            create_backup(self.items_path, self.backup_dir, self.settings["backup"])
        self.purchases_tab.refresh()

    def save_money(self, trigger_backup: bool = True) -> None:
        write_money(self.money_path, self.money)
        if trigger_backup:
            create_backup(self.money_path, self.backup_dir, self.settings["backup"])
        self.money_tab.refresh()

    def add_or_edit_item(self, existing: Optional[ItemRecord] = None) -> None:
        dialog = ItemDialog(self, existing)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            record = dialog.result_record
            scored: ScoreResult = score_item(record, self.weights)
            record.overall_score = scored.overall
            if existing:
                self.items = [record if i.id == existing.id else i for i in self.items]
            else:
                self.items.append(record)
            self._sort_items()
            self.save_items(trigger_backup=self.settings["ui"].get("autosave", True))

    def view_item(self, record: ItemRecord) -> None:
        msg = QtWidgets.QMessageBox(self)
        msg.setWindowTitle("Item Details")
        msg.setIcon(QtWidgets.QMessageBox.Information)
        details = [
            f"Product: {record.product}",
            f"Date: {record.date.strftime(self.date_fmt)}",
            f"Cost: {self.currency_symbol}{record.cost:.2f}",
            f"Urgency: {record.urgency}",
            f"Value: {record.value}",
            f"Price vs Similar: {record.price_comp}",
            f"Effect: {record.effect}",
            f"Justification: {record.justification}",
            f"Reference: {record.reference}",
            f"Location: {record.location}",
            f"Recurrence: {record.recurrence}",
            f"Overall Score: {(record.overall_score or 0):.2f}",
        ]
        msg.setText("\n".join(details))
        msg.exec()

    def add_or_edit_money(self, existing: Optional[MoneyRecord] = None) -> None:
        dialog = MoneyDialog(self, existing, self.items)
        if dialog.exec() == QtWidgets.QDialog.Accepted:
            record = dialog.result_record
            if existing:
                self.money = [record if m.id == existing.id else m for m in self.money]
            else:
                self.money.append(record)
            self._sort_money()
            self.save_money(trigger_backup=self.settings["ui"].get("autosave", True))


class PurchasesWidget(QtWidgets.QWidget):
    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self.main = main
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(_section_label("Purchases"))

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        controls.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.textChanged.connect(self.refresh)
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItems(["All", "High (>4)", "Low (<2.5)"])
        self.filter_combo.currentIndexChanged.connect(self.refresh)

        for text, handler in [
            ("Add Item", self.add_item),
            ("Edit", self.edit_item),
            ("View", self.view_item),
            ("Delete", self.delete_item),
            ("Import CSV", self.import_csv),
            ("Export CSV", self.export_csv),
            ("Refresh", self.refresh),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(handler)
            controls.addWidget(btn)

        controls.addStretch()
        controls.addWidget(QtWidgets.QLabel("Filter"))
        controls.addWidget(self.filter_combo)
        controls.addWidget(self.search_edit)
        layout.addLayout(controls)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Product", "Date", "Cost", "Urgency", "Overall"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_item)
        layout.addWidget(self.table)

        summary = QtWidgets.QHBoxLayout()
        self.total_label = QtWidgets.QLabel("Total: 0")
        self.avg_label = QtWidgets.QLabel("Average: 0")
        self.count_label = QtWidgets.QLabel("Items: 0")
        for lbl in (self.total_label, self.avg_label, self.count_label):
            summary.addWidget(lbl)
        summary.addStretch()
        layout.addLayout(summary)

    def _filtered_items(self) -> List[ItemRecord]:
        query = self.search_edit.text().strip().lower()
        mode = self.filter_combo.currentText()
        filtered = []
        for item in self.main.items:
            haystack = " ".join(
                [item.product, item.description, item.location, item.reference, item.justification]
            ).lower()
            if query and query not in haystack:
                continue
            if mode.startswith("High") and (item.overall_score or 0) <= 4:
                continue
            if mode.startswith("Low") and (item.overall_score or 0) >= 2.5:
                continue
            filtered.append(item)
        return filtered

    def refresh(self) -> None:
        items = self._filtered_items()
        self.table.setRowCount(len(items))
        total = 0.0
        score_sum = 0.0
        scored = 0
        for row, item in enumerate(items):
            values = [
                item.product,
                item.date.strftime(self.main.date_fmt),
                f"{self.main.currency_symbol}{item.cost:.2f}",
                str(item.urgency),
                f"{(item.overall_score or 0):.2f}",
            ]
            for col, val in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(val)
                if col == 0:
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole, item.id)
                self.table.setItem(row, col, cell)
            total += item.cost
            if item.overall_score is not None:
                scored += 1
                score_sum += item.overall_score
        avg = score_sum / scored if scored else 0.0
        self.total_label.setText(f"Total: {self.main.currency_symbol}{total:.2f}")
        self.avg_label.setText(f"Average: {avg:.2f}")
        self.count_label.setText(f"Items: {len(items)}")

    def _selected_item(self) -> Optional[ItemRecord]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        item_id = self.table.item(row, 0).data(QtCore.Qt.ItemDataRole.UserRole)
        # store id in hidden? easier: match by displayed product? Instead map using sorted order:
        filtered = self._filtered_items()
        if row < len(filtered):
            return filtered[row]
        return None

    def add_item(self) -> None:
        self.main.add_or_edit_item()

    def edit_item(self) -> None:
        record = self._selected_item()
        if record:
            self.main.add_or_edit_item(record)

    def view_item(self) -> None:
        record = self._selected_item()
        if record:
            self.main.view_item(record)

    def delete_item(self) -> None:
        record = self._selected_item()
        if not record:
            return
        if QtWidgets.QMessageBox.question(self, "Delete", f"Delete '{record.product}'?") == QtWidgets.QMessageBox.Yes:
            self.main.items = [i for i in self.main.items if i.id != record.id]
            self.main.save_items(trigger_backup=self.main.settings["ui"].get("autosave", True))

    def import_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select items CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            imported = read_items(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Import failed", str(exc))
            return
        choice = QtWidgets.QMessageBox.question(
            self,
            "Import Items",
            "Replace existing items with imported data?\nYes = replace, No = append.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.main.items = imported
        else:
            merged = {i.id: i for i in self.main.items}
            for i in imported:
                merged[i.id] = i
            self.main.items = list(merged.values())
        self.main._sort_items()
        self.main.save_items(trigger_backup=self.main.settings["ui"].get("autosave", True))
        QtWidgets.QMessageBox.information(self, "Import", "Items imported.")

    def export_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save items CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            write_items(path, self._filtered_items())
            QtWidgets.QMessageBox.information(self, "Export", "Items exported.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))


class MoneyWidget(QtWidgets.QWidget):
    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self.main = main
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.addWidget(_section_label("Money"))

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        controls.setContentsMargins(0, 0, 0, 0)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.textChanged.connect(self.refresh)
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItems(["All", "Income", "Expense"])
        self.type_filter.currentIndexChanged.connect(self.refresh)

        for text, handler in [
            ("Add Entry", self.add_entry),
            ("Edit", self.edit_entry),
            ("Delete", self.delete_entry),
            ("Import CSV", self.import_csv),
            ("Export CSV", self.export_csv),
            ("Refresh", self.refresh),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(handler)
            controls.addWidget(btn)

        controls.addStretch()
        controls.addWidget(QtWidgets.QLabel("Type"))
        controls.addWidget(self.type_filter)
        controls.addWidget(self.search_edit)
        layout.addLayout(controls)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Type", "Source/Destination", "Amount", "Linked Item"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.horizontalHeader().setDefaultAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter)
        self.table.horizontalHeader().setHighlightSections(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(38)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_entry)
        layout.addWidget(self.table)

        summary = QtWidgets.QHBoxLayout()
        self.income_label = QtWidgets.QLabel("Income: 0")
        self.expense_label = QtWidgets.QLabel("Expenses: 0")
        self.balance_label = QtWidgets.QLabel("Balance: 0")
        for lbl in (self.income_label, self.expense_label, self.balance_label):
            summary.addWidget(lbl)
        summary.addStretch()
        layout.addLayout(summary)

    def _filtered_entries(self) -> List[MoneyRecord]:
        query = self.search_edit.text().strip().lower()
        type_mode = self.type_filter.currentText().lower()
        id_to_product = {item.id: item.product for item in self.main.items}
        results = []
        for entry in self.main.money:
            haystack = " ".join(
                [
                    entry.entry_type,
                    entry.source_or_destination,
                    entry.notes,
                    entry.linked_item_id,
                    id_to_product.get(entry.linked_item_id, ""),
                ]
            ).lower()
            if query and query not in haystack:
                continue
            if type_mode == "income" and entry.entry_type.lower() != "income":
                continue
            if type_mode == "expense" and entry.entry_type.lower() != "expense":
                continue
            results.append(entry)
        return results

    def refresh(self) -> None:
        entries = self._filtered_entries()
        self.table.setRowCount(len(entries))
        income = 0.0
        expense = 0.0
        for row, entry in enumerate(entries):
            if entry.entry_type.lower() == "income":
                income += entry.amount
            elif entry.entry_type.lower() == "expense":
                expense += entry.amount
            values = [
                entry.date.strftime(self.main.date_fmt),
                entry.entry_type.title(),
                entry.source_or_destination,
                f"{self.main.currency_symbol}{entry.amount:.2f}",
                entry.linked_item_id,
            ]
            for col, val in enumerate(values):
                cell = QtWidgets.QTableWidgetItem(val)
                if col == 0:
                    cell.setData(QtCore.Qt.ItemDataRole.UserRole, entry.id)
                self.table.setItem(row, col, cell)
        balance = income - expense
        self.income_label.setText(f"Income: {self.main.currency_symbol}{income:.2f}")
        self.expense_label.setText(f"Expenses: {self.main.currency_symbol}{expense:.2f}")
        self.balance_label.setText(f"Balance: {self.main.currency_symbol}{balance:.2f}")

    def _selected_entry(self) -> Optional[MoneyRecord]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
        entries = self._filtered_entries()
        if row < len(entries):
            return entries[row]
        return None

    def add_entry(self) -> None:
        self.main.add_or_edit_money()

    def edit_entry(self) -> None:
        record = self._selected_entry()
        if record:
            self.main.add_or_edit_money(record)

    def delete_entry(self) -> None:
        record = self._selected_entry()
        if not record:
            return
        if QtWidgets.QMessageBox.question(self, "Delete", "Delete this entry?") == QtWidgets.QMessageBox.Yes:
            self.main.money = [m for m in self.main.money if m.id != record.id]
            self.main.save_money(trigger_backup=self.main.settings["ui"].get("autosave", True))

    def import_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select money CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            imported = read_money(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Import failed", str(exc))
            return
        choice = QtWidgets.QMessageBox.question(
            self,
            "Import Money",
            "Replace existing entries with imported data?\nYes = replace, No = append.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.main.money = imported
        else:
            merged = {m.id: m for m in self.main.money}
            for m in imported:
                merged[m.id] = m
            self.main.money = list(merged.values())
        self.main._sort_money()
        self.main.save_money(trigger_backup=self.main.settings["ui"].get("autosave", True))
        QtWidgets.QMessageBox.information(self, "Import", "Money entries imported.")

    def export_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save money CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            write_money(path, self._filtered_entries())
            QtWidgets.QMessageBox.information(self, "Export", "Money entries exported.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))


class SettingsWidget(QtWidgets.QWidget):
    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self.main = main
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QFormLayout(self)
        layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        layout.addRow(_section_label("Preferences"))
        self.autosave_check = QtWidgets.QCheckBox("Enable autosave")
        self.autosave_check.setChecked(self.main.settings["ui"].get("autosave", True))
        self.autosave_check.stateChanged.connect(self._toggle_autosave)
        layout.addRow("Autosave", self.autosave_check)

        backup_btn = QtWidgets.QPushButton("Backup now")
        backup_btn.clicked.connect(self._backup_now)
        open_btn = QtWidgets.QPushButton("Open data folder")
        open_btn.clicked.connect(self._open_data_dir)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(backup_btn)
        btn_row.addWidget(open_btn)
        layout.addRow("Data", btn_row)

        self._add_path_row(layout, "Items file", self.main.items_path)
        self._add_path_row(layout, "Money file", self.main.money_path)
        self._add_path_row(layout, "Backups", self.main.backup_dir)

    def _toggle_autosave(self, state: int) -> None:
        self.main.settings["ui"]["autosave"] = bool(state)
        self.main.config_manager.save_settings()

    def _backup_now(self) -> None:
        try:
            create_backup(self.main.items_path, self.main.backup_dir, self.main.settings["backup"])
            create_backup(self.main.money_path, self.main.backup_dir, self.main.settings["backup"])
            QtWidgets.QMessageBox.information(self, "Backup", "Backups created.")
        except FileNotFoundError as exc:
            QtWidgets.QMessageBox.critical(self, "Backup failed", str(exc))

    def _open_data_dir(self) -> None:
        for path in [
            Path(self.main.items_path).parent,
            Path(self.main.money_path).parent,
            Path(self.main.backup_dir),
        ]:
            if path:
                path.mkdir(parents=True, exist_ok=True)
                target = str(path)
                if sys.platform.startswith("win"):
                    os.startfile(target)  # type: ignore[attr-defined]
                elif sys.platform == "darwin":
                    subprocess.Popen(["open", target])
                else:
                    subprocess.Popen(["xdg-open", target])
                return
        QtWidgets.QMessageBox.information(self, "Open folder", "Data folder not found yet. Save data first.")

    def _add_path_row(self, layout: QtWidgets.QFormLayout, label: str, path: str) -> None:
        row = QtWidgets.QHBoxLayout()
        entry = QtWidgets.QLineEdit(path)
        entry.setReadOnly(True)
        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(path))
        row.addWidget(entry)
        row.addWidget(copy_btn)
        layout.addRow(label, row)


class ItemDialog(QtWidgets.QDialog):
    def __init__(self, main: MainWindow, existing: Optional[ItemRecord]) -> None:
        super().__init__(main)
        self.main = main
        self.result_record: Optional[ItemRecord] = None
        self.existing = existing
        self.setWindowTitle("Item" if not existing else "Edit Item")
        self._build_ui()
        if existing:
            self._load(existing)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(_section_label("Item Details"))
        info_form = QtWidgets.QFormLayout()
        info_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        info_form.setSpacing(10)
        info_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.date_edit = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.date_edit.setMinimumWidth(280)

        self.product = QtWidgets.QLineEdit()
        self.description = QtWidgets.QLineEdit()
        self.location = QtWidgets.QLineEdit()
        self.reference = QtWidgets.QLineEdit()
        self.cost = QtWidgets.QDoubleSpinBox()
        self.cost.setMaximum(1_000_000)
        self.cost.setPrefix(self.main.currency_symbol)
        self.urgency = QtWidgets.QSpinBox()
        self.urgency.setRange(1, 5)
        self.value = QtWidgets.QSpinBox()
        self.value.setRange(1, 5)
        self.price_comp = QtWidgets.QSpinBox()
        self.price_comp.setRange(1, 5)
        self.effect = QtWidgets.QSpinBox()
        self.effect.setRange(1, 5)
        self.justification = QtWidgets.QLineEdit()
        self.recurrence = QtWidgets.QComboBox()
        self.recurrence.addItems(["none", "once", "weekly", "biweekly", "monthly", "quarterly", "yearly"])
        field_width = 320
        for widget in [
            self.product,
            self.description,
            self.location,
            self.reference,
            self.cost,
            self.urgency,
            self.value,
            self.price_comp,
            self.effect,
            self.justification,
            self.recurrence,
        ]:
            widget.setMinimumWidth(field_width)

        info_form.addRow("Date", self.date_edit)
        info_form.addRow("Product", self.product)
        info_form.addRow("Description", self.description)
        info_form.addRow("Location", self.location)
        info_form.addRow("Reference", self.reference)
        layout.addLayout(info_form)

        layout.addWidget(_section_label("Scoring & Recurrence"))
        score_form = QtWidgets.QFormLayout()
        score_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        score_form.setSpacing(10)
        score_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        score_form.addRow("Cost", self.cost)
        score_form.addRow("Urgency", self.urgency)
        score_form.addRow("Value", self.value)
        score_form.addRow("Price vs Similar", self.price_comp)
        score_form.addRow("Effect", self.effect)
        score_form.addRow("Justification", self.justification)
        score_form.addRow("Recurrence", self.recurrence)
        layout.addLayout(score_form)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

    def _load(self, item: ItemRecord) -> None:
        self.date_edit.setDateTime(QtCore.QDateTime.fromString(item.date.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        self.product.setText(item.product)
        self.description.setText(item.description)
        self.location.setText(item.location)
        self.reference.setText(item.reference)
        self.cost.setValue(item.cost)
        self.urgency.setValue(item.urgency)
        self.value.setValue(item.value)
        self.price_comp.setValue(item.price_comp)
        self.effect.setValue(item.effect)
        self.justification.setText(item.justification)
        if item.recurrence:
            idx = self.recurrence.findText(item.recurrence)
            if idx >= 0:
                self.recurrence.setCurrentIndex(idx)

    def _save(self) -> None:
        try:
            date = self.date_edit.dateTime().toPython()
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid", "Invalid date.")
            return
        record = ItemRecord(
            id=self.existing.id if self.existing else str(QtCore.QUuid.createUuid()).strip("{}"),
            date=date,
            product=self.product.text(),
            description=self.description.text(),
            location=self.location.text(),
            reference=self.reference.text(),
            cost=float(self.cost.value()),
            urgency=int(self.urgency.value()),
            value=int(self.value.value()),
            price_comp=int(self.price_comp.value()),
            effect=int(self.effect.value()),
            justification=self.justification.text(),
            recurrence=self.recurrence.currentText(),
        )
        self.result_record = record
        self.accept()


class MoneyDialog(QtWidgets.QDialog):
    def __init__(self, main: MainWindow, existing: Optional[MoneyRecord], items: List[ItemRecord]) -> None:
        super().__init__(main)
        self.main = main
        self.items = items
        self.result_record: Optional[MoneyRecord] = None
        self.existing = existing
        self.setWindowTitle("Money Entry" if not existing else "Edit Money Entry")
        self._build_ui()
        if existing:
            self._load(existing)

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(18, 18, 18, 18)

        layout.addWidget(_section_label("Money Entry"))
        info_form = QtWidgets.QFormLayout()
        info_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        info_form.setSpacing(10)
        info_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        self.date_edit = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.date_edit.setMinimumWidth(280)

        self.type_box = QtWidgets.QComboBox()
        self.type_box.addItems(["income", "expense"])
        self.source = QtWidgets.QLineEdit()
        self.amount = QtWidgets.QDoubleSpinBox()
        self.amount.setMaximum(10_000_000)
        self.amount.setPrefix(self.main.currency_symbol)
        self.notes = QtWidgets.QLineEdit()
        self.link_combo = QtWidgets.QComboBox()
        self.link_combo.addItem("", "")
        for item in self.items:
            self.link_combo.addItem(f"{item.product} ({item.id})", item.id)

        for widget in [self.type_box, self.source, self.amount, self.notes, self.link_combo]:
            widget.setMinimumWidth(320)

        info_form.addRow("Date", self.date_edit)
        info_form.addRow("Type", self.type_box)
        info_form.addRow("Source/Destination", self.source)
        info_form.addRow("Amount", self.amount)
        layout.addLayout(info_form)

        layout.addWidget(_section_label("Notes & Linking"))
        extras_form = QtWidgets.QFormLayout()
        extras_form.setLabelAlignment(QtCore.Qt.AlignRight | QtCore.Qt.AlignVCenter)
        extras_form.setSpacing(10)
        extras_form.setFieldGrowthPolicy(QtWidgets.QFormLayout.AllNonFixedFieldsGrow)
        extras_form.addRow("Notes", self.notes)
        extras_form.addRow("Linked Item", self.link_combo)
        layout.addLayout(extras_form)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addStretch()
        btn_row.addWidget(buttons)
        layout.addLayout(btn_row)

    def _load(self, entry: MoneyRecord) -> None:
        self.date_edit.setDateTime(QtCore.QDateTime.fromString(entry.date.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        self.type_box.setCurrentText(entry.entry_type)
        self.source.setText(entry.source_or_destination)
        self.amount.setValue(entry.amount)
        self.notes.setText(entry.notes)
        idx = self.link_combo.findData(entry.linked_item_id)
        if idx >= 0:
            self.link_combo.setCurrentIndex(idx)

    def _save(self) -> None:
        try:
            date = self.date_edit.dateTime().toPython()
        except Exception:
            QtWidgets.QMessageBox.warning(self, "Invalid", "Invalid date.")
            return
        record = MoneyRecord(
            id=self.existing.id if self.existing else str(QtCore.QUuid.createUuid()).strip("{}"),
            date=date,
            entry_type=self.type_box.currentText(),
            source_or_destination=self.source.text(),
            amount=float(self.amount.value()),
            notes=self.notes.text(),
            linked_item_id=self.link_combo.currentData() or "",
        )
        self.result_record = record
        self.accept()


if __name__ == "__main__":
    launch()


def _detach_console_on_windows() -> None:
    if sys.platform.startswith("win") and hasattr(ctypes, "windll"):
        try:
            ctypes.windll.kernel32.FreeConsole()
        except Exception:
            pass
