from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from PySide6 import QtCore, QtGui, QtWidgets

from core.backup import create_backup
from core.config_manager import ConfigManager, ensure_paths, ensure_startup_files
from core.csv_storage import read_bundle, read_items, read_money, write_bundle, write_items, write_money
from core.models import DATE_FMT, ItemRecord, MoneyRecord
from scoring.scoring import ScoreResult, score_item


def _merge_by_id(existing, imported):
    merged = {record.id: record for record in existing}
    for record in imported:
        merged[record.id] = record
    return list(merged.values())


def launch() -> None:
    _detach_console_on_windows()
    _redirect_stdio_to_null_on_windows()
    app = QtWidgets.QApplication(sys.argv)
    config = ConfigManager()
    ensure_paths(config.settings)
    ensure_startup_files(config)
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
        self.item_sort_column, self.item_sort_ascending = self._load_sort_state(
            "items_sort", default_column=1, default_direction="desc"
        )
        self.money_sort_column, self.money_sort_ascending = self._load_sort_state(
            "money_sort", default_column=0, default_direction="desc"
        )

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
        layout.setContentsMargins(12, 12, 12, 12)
        layout.addWidget(self.tabs)
        self.setCentralWidget(container)
        self.setMinimumSize(960, 640)

        self._load_data()
        self._setup_shortcuts()
        self._show_config_messages()

    def _load_sort_state(self, key: str, default_column: int, default_direction: str) -> tuple[int, bool]:
        ui_settings = self.settings.setdefault("ui", {})
        sort_cfg = ui_settings.get(key, {})
        changed = False
        if not isinstance(sort_cfg, dict):
            sort_cfg = {}
            ui_settings[key] = sort_cfg
            changed = True
        column = int(sort_cfg.get("column", default_column))
        direction = sort_cfg.get("direction", default_direction)
        if "column" not in sort_cfg:
            sort_cfg["column"] = column
            changed = True
        if "direction" not in sort_cfg:
            sort_cfg["direction"] = direction
            changed = True
        if changed:
            self.config_manager.save_settings()
        return column, direction == "asc"

    def _persist_sort_state(self, key: str, column: int, ascending: bool) -> None:
        self.settings["ui"][key] = {"column": column, "direction": "asc" if ascending else "desc"}
        self.config_manager.save_settings()

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
        self._rescore_items()
        self.purchases_tab.refresh()
        self.money_tab.refresh()

    def _sort_items(self) -> None:
        col = self.item_sort_column
        asc = self.item_sort_ascending
        if col == 0:
            self.items.sort(key=lambda i: i.product.lower(), reverse=not asc)
        elif col == 1:
            self.items.sort(key=lambda i: i.date, reverse=not asc)
        elif col == 2:
            self.items.sort(key=lambda i: i.cost, reverse=not asc)
        elif col == 3:
            self.items.sort(key=lambda i: i.urgency, reverse=not asc)
        elif col == 4:
            self.items.sort(
                key=lambda i: (
                    i.overall_score is None,
                    (i.overall_score or 0.0) if asc else -(i.overall_score or 0.0),
                )
            )
        else:
            self.items.sort(key=lambda i: i.date, reverse=True)
            self.item_sort_column = 1
            self.item_sort_ascending = False

    def _sort_money(self) -> None:
        col = self.money_sort_column
        asc = self.money_sort_ascending
        linked_names = {item.id: item.product for item in self.items}
        if col == 0:
            self.money.sort(key=lambda m: m.date, reverse=not asc)
        elif col == 1:
            self.money.sort(key=lambda m: m.entry_type.lower(), reverse=not asc)
        elif col == 2:
            self.money.sort(key=lambda m: m.source_or_destination.lower(), reverse=not asc)
        elif col == 3:
            self.money.sort(key=lambda m: m.amount, reverse=not asc)
        elif col == 4:
            self.money.sort(
                key=lambda m: linked_names.get(m.linked_item_id, m.linked_item_id).lower(), reverse=not asc
            )
        else:
            self.money.sort(key=lambda m: m.date, reverse=True)
            self.money_sort_column = 0
            self.money_sort_ascending = False

    def _rescore_items(self) -> None:
        for item in self.items:
            item.overall_score = score_item(item, self.weights).overall

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

    def _show_config_messages(self) -> None:
        restart_note = "Edit weights in weights.txt and restart the app to apply changes."
        if self.config_manager.load_messages:
            messages = list(self.config_manager.load_messages)
            messages.append(restart_note)
            QtWidgets.QMessageBox.warning(self, "Configuration", "\n".join(messages))
        else:
            print(restart_note)

    def view_item(self, record: ItemRecord) -> None:
        dialog = ItemViewDialog(self, record, self.date_fmt, self.currency_symbol)
        dialog.exec()

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


class ItemViewDialog(QtWidgets.QDialog):
    def __init__(self, parent: MainWindow, record: ItemRecord, date_fmt: str, currency_symbol: str) -> None:
        super().__init__(parent)
        self.setWindowTitle("Item Details")
        self.setMinimumWidth(520)
        self._build_ui(record, date_fmt, currency_symbol)

    def _build_ui(self, record: ItemRecord, date_fmt: str, currency_symbol: str) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(10)
        icon_label = QtWidgets.QLabel()
        icon = self.style().standardIcon(QtWidgets.QStyle.SP_FileDialogInfoView)
        icon_label.setPixmap(icon.pixmap(32, 32))
        header.addWidget(icon_label)

        title = QtWidgets.QLabel(record.product or "Item")
        title_font = title.font()
        title_font.setPointSize(title_font.pointSize() + 2)
        title_font.setBold(True)
        title.setFont(title_font)
        header.addWidget(title)
        header.addStretch()
        layout.addLayout(header)

        details_section, details_layout = self._section_container(
            "Details", QtWidgets.QStyle.SP_FileDialogDetailedView
        )
        details_form = QtWidgets.QFormLayout()
        details_form.setLabelAlignment(QtCore.Qt.AlignRight)
        details_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        details_form.setHorizontalSpacing(14)
        details_form.setVerticalSpacing(8)

        def add_detail(label: str, widget: QtWidgets.QWidget) -> None:
            details_form.addRow(self._section_label(label), widget)

        add_detail("Date", self._readonly_field(record.date.strftime(date_fmt)))
        add_detail("Cost", self._readonly_field(f"{currency_symbol}{record.cost:,.2f}"))
        add_detail("Location", self._readonly_field(record.location))
        add_detail("Recurrence", self._readonly_field(record.recurrence))
        add_detail("Reference", self._readonly_field(record.reference, multiline=True))

        details_layout.addLayout(details_form)

        eval_section, eval_layout = self._section_container("Evaluation", QtWidgets.QStyle.SP_DialogApplyButton)
        eval_form = QtWidgets.QFormLayout()
        eval_form.setLabelAlignment(QtCore.Qt.AlignRight)
        eval_form.setFormAlignment(QtCore.Qt.AlignLeft | QtCore.Qt.AlignTop)
        eval_form.setHorizontalSpacing(14)
        eval_form.setVerticalSpacing(8)

        def add_eval(label: str, widget: QtWidgets.QWidget) -> None:
            eval_form.addRow(self._section_label(label), widget)

        add_eval("Urgency", self._readonly_field(str(record.urgency)))
        add_eval("Value", self._readonly_field(str(record.value)))
        add_eval("Want", self._readonly_field(str(record.want)))
        add_eval("Price vs Similar", self._readonly_field(str(record.price_comp)))
        add_eval("Effect", self._readonly_field(str(record.effect)))
        add_eval("Overall Score", self._readonly_field(f"{(record.overall_score or 0):.2f}"))
        add_eval("Description", self._readonly_field(record.description, multiline=True))
        add_eval("Justification", self._readonly_field(record.justification, multiline=True))

        eval_layout.addLayout(eval_form)

        layout.addWidget(details_section)
        layout.addWidget(eval_section)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Close)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        close_btn = buttons.button(QtWidgets.QDialogButtonBox.Close)
        if close_btn:
            close_btn.setDefault(True)
        layout.addWidget(buttons)

    def _section_container(
        self, title: str, icon_type: QtWidgets.QStyle.StandardPixmap
    ) -> tuple[QtWidgets.QGroupBox, QtWidgets.QVBoxLayout]:
        box = QtWidgets.QGroupBox()
        box_layout = QtWidgets.QVBoxLayout(box)
        box_layout.setContentsMargins(10, 10, 10, 10)
        box_layout.setSpacing(8)

        header = QtWidgets.QHBoxLayout()
        header.setSpacing(6)
        icon_label = QtWidgets.QLabel()
        icon = self.style().standardIcon(icon_type)
        icon_label.setPixmap(icon.pixmap(20, 20))
        header.addWidget(icon_label)

        label = QtWidgets.QLabel(title)
        label_font = label.font()
        label_font.setBold(True)
        label.setFont(label_font)
        header.addWidget(label)
        header.addStretch()
        box_layout.addLayout(header)
        return box, box_layout

    def _readonly_field(self, text: str, multiline: bool = False) -> QtWidgets.QWidget:
        if multiline:
            widget: QtWidgets.QPlainTextEdit = QtWidgets.QPlainTextEdit()
            widget.setPlainText(text)
            widget.setReadOnly(True)
            widget.setFrameStyle(QtWidgets.QFrame.Panel | QtWidgets.QFrame.Sunken)
            widget.setBackgroundVisible(False)
            widget.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)
            widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarAlwaysOff)
            widget.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
            widget.setMinimumHeight(64)
            return widget
        line_edit = QtWidgets.QLineEdit(text)
        line_edit.setReadOnly(True)
        line_edit.setFrame(True)
        return line_edit

    def _section_label(self, text: str) -> QtWidgets.QLabel:
        label = QtWidgets.QLabel(text)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        return label


class PurchasesWidget(QtWidgets.QWidget):
    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self.main = main
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.textChanged.connect(self.refresh)
        self.filter_combo = QtWidgets.QComboBox()
        self.filter_combo.addItems(["All", "High (>4)", "Low (<2.5)"])
        self.filter_combo.currentIndexChanged.connect(self.refresh)
        clear_btn = QtWidgets.QPushButton("Clear Filters")
        clear_btn.clicked.connect(self._clear_filters)

        for text, handler in [
            ("Add Item", self.add_item),
            ("Edit", self.edit_item),
            ("View", self.view_item),
            ("Delete", self.delete_item),
            ("Import", self.import_data),
            ("Export", self.export_data),
            ("Refresh", self.refresh),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(handler)
            controls.addWidget(btn)

        controls.addStretch()
        controls.addWidget(QtWidgets.QLabel("Filter"))
        controls.addWidget(self.filter_combo)
        controls.addWidget(self.search_edit)
        controls.addWidget(clear_btn)
        layout.addLayout(controls)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Product", "Date", "Cost", "Urgency", "Want", "Overall"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_item)
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._handle_sort)
        self.table.setSortingEnabled(False)
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
        self.table.setSortingEnabled(False)
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
                str(item.want),
                f"{(item.overall_score or 0):.2f}",
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(val))
            total += item.cost
            if item.overall_score is not None:
                scored += 1
                score_sum += item.overall_score
        sort_order = QtCore.Qt.AscendingOrder if self.main.item_sort_ascending else QtCore.Qt.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(self.main.item_sort_column, sort_order)
        avg = score_sum / scored if scored else 0.0
        self.total_label.setText(f"Total: {self.main.currency_symbol}{total:.2f}")
        self.avg_label.setText(f"Average: {avg:.2f}")
        self.count_label.setText(f"Items: {len(items)}")

    def _selected_item(self) -> Optional[ItemRecord]:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        row = rows[0].row()
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

    def import_data(self) -> None:
        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Import",
            "Select data type to import:",
            ["Items (CSV)", "Money (CSV)", "Bundle (JSON)"],
            0,
            False,
        )
        if not ok:
            return
        if choice.startswith("Items"):
            self._import_items_csv()
        elif choice.startswith("Money"):
            self._import_money_csv()
        else:
            self._import_bundle()

    def export_data(self) -> None:
        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Export",
            "Select data to export:",
            ["Items (CSV)", "Money (CSV)", "Bundle (JSON)"],
            0,
            False,
        )
        if not ok:
            return
        if choice.startswith("Items"):
            self._export_items_csv()
        elif choice.startswith("Money"):
            self._export_money_csv()
        else:
            self._export_bundle()

    def _import_items_csv(self) -> None:
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
            self.main.items = _merge_by_id(self.main.items, imported)
        self.main._sort_items()
        self.main.save_items(trigger_backup=self.main.settings["ui"].get("autosave", True))
        QtWidgets.QMessageBox.information(self, "Import", "Items imported.")

    def _export_items_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save items CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            write_items(path, self._filtered_items())
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))
        else:
            QtWidgets.QMessageBox.information(self, "Export", "Items exported.")

    def _import_money_csv(self) -> None:
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
            "Replace existing money entries with imported data?\nYes = replace, No = append.",
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.main.money = imported
        else:
            self.main.money = _merge_by_id(self.main.money, imported)
        self.main._sort_money()
        self.main.save_money(trigger_backup=self.main.settings["ui"].get("autosave", True))
        QtWidgets.QMessageBox.information(self, "Import", "Money entries imported.")

    def _export_money_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save money CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            write_money(path, self.main.money)
            QtWidgets.QMessageBox.information(self, "Export", "Money entries exported.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))

    def _import_bundle(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select bundle", filter="Bundle Files (*.json)")
        if not path:
            return
        try:
            items, money, metadata = read_bundle(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Import failed", f"Could not read bundle:\n{exc}")
            return
        details = metadata.get("generated_at", "unknown time") if isinstance(metadata, dict) else "unknown time"
        choice = QtWidgets.QMessageBox.question(
            self,
            "Import Bundle",
            (
                f"Bundle contains {len(items)} items and {len(money)} money entries "
                f"(created {details}).\n\n"
                "Yes = overwrite current items and money with bundle contents.\n"
                "No = append/merge; incoming records replace matching IDs and new IDs are added."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.main.items = items
            self.main.money = money
        else:
            self.main.items = _merge_by_id(self.main.items, items)
            self.main.money = _merge_by_id(self.main.money, money)
        self.main._sort_items()
        self.main._sort_money()
        autosave = self.main.settings["ui"].get("autosave", True)
        self.main.save_items(trigger_backup=autosave)
        self.main.save_money(trigger_backup=autosave)
        QtWidgets.QMessageBox.information(self, "Import", "Bundle imported.")

    def _export_bundle(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save bundle", filter="Bundle Files (*.json)")
        if not path:
            return
        try:
            write_bundle(path, self.main.items, self.main.money)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", f"Could not write bundle:\n{exc}")
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Export",
                f"Bundle exported with {len(self.main.items)} items and {len(self.main.money)} money entries.",
            )

    def _clear_filters(self) -> None:
        self.search_edit.clear()
        self.filter_combo.setCurrentIndex(0)

    def _handle_sort(self, column: int) -> None:
        if column == self.main.item_sort_column:
            self.main.item_sort_ascending = not self.main.item_sort_ascending
        else:
            self.main.item_sort_column = column
            self.main.item_sort_ascending = True
        self.main._persist_sort_state("items_sort", self.main.item_sort_column, self.main.item_sort_ascending)
        self.main._sort_items()
        self.refresh()


class MoneyWidget(QtWidgets.QWidget):
    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self.main = main
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QVBoxLayout(self)
        layout.setSpacing(8)

        controls = QtWidgets.QHBoxLayout()
        controls.setSpacing(6)
        self.search_edit = QtWidgets.QLineEdit()
        self.search_edit.setPlaceholderText("Search")
        self.search_edit.textChanged.connect(self.refresh)
        self.type_filter = QtWidgets.QComboBox()
        self.type_filter.addItems(["All", "Income", "Expense"])
        self.type_filter.currentIndexChanged.connect(self.refresh)
        clear_btn = QtWidgets.QPushButton("Clear Filters")
        clear_btn.clicked.connect(self._clear_filters)

        for text, handler in [
            ("Add Entry", self.add_entry),
            ("Edit", self.edit_entry),
            ("Delete", self.delete_entry),
            ("Import", self.import_data),
            ("Export", self.export_data),
            ("Refresh", self.refresh),
        ]:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(handler)
            controls.addWidget(btn)

        controls.addStretch()
        controls.addWidget(QtWidgets.QLabel("Type"))
        controls.addWidget(self.type_filter)
        controls.addWidget(self.search_edit)
        controls.addWidget(clear_btn)
        layout.addLayout(controls)

        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Date", "Type", "Source/Destination", "Amount", "Linked Item"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.table.doubleClicked.connect(self.edit_entry)
        header = self.table.horizontalHeader()
        header.setSortIndicatorShown(True)
        header.sectionClicked.connect(self._handle_sort)
        self.table.setSortingEnabled(False)
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
        id_to_product = {item.id: item.product for item in self.main.items}
        entries = self._filtered_entries()
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(entries))
        income = 0.0
        expense = 0.0
        for row, entry in enumerate(entries):
            if entry.entry_type.lower() == "income":
                income += entry.amount
            elif entry.entry_type.lower() == "expense":
                expense += entry.amount
            linked_display = id_to_product.get(entry.linked_item_id, entry.linked_item_id)
            values = [
                entry.date.strftime(self.main.date_fmt),
                entry.entry_type.title(),
                entry.source_or_destination,
                f"{self.main.currency_symbol}{entry.amount:.2f}",
                linked_display,
            ]
            for col, val in enumerate(values):
                self.table.setItem(row, col, QtWidgets.QTableWidgetItem(val))
        sort_order = QtCore.Qt.AscendingOrder if self.main.money_sort_ascending else QtCore.Qt.DescendingOrder
        self.table.horizontalHeader().setSortIndicator(self.main.money_sort_column, sort_order)
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

    def import_data(self) -> None:
        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Import",
            "Select data type to import:",
            ["Money (CSV)", "Items (CSV)", "Bundle (JSON)"],
            0,
            False,
        )
        if not ok:
            return
        if choice.startswith("Money"):
            self._import_money_csv()
        elif choice.startswith("Items"):
            self._import_items_csv()
        else:
            self._import_bundle()

    def export_data(self) -> None:
        choice, ok = QtWidgets.QInputDialog.getItem(
            self,
            "Export",
            "Select data to export:",
            ["Money (CSV)", "Items (CSV)", "Bundle (JSON)"],
            0,
            False,
        )
        if not ok:
            return
        if choice.startswith("Money"):
            self._export_money_csv()
        elif choice.startswith("Items"):
            self._export_items_csv()
        else:
            self._export_bundle()

    def _import_money_csv(self) -> None:
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
            self.main.money = _merge_by_id(self.main.money, imported)
        self.main._sort_money()
        self.main.save_money(trigger_backup=self.main.settings["ui"].get("autosave", True))
        QtWidgets.QMessageBox.information(self, "Import", "Money entries imported.")

    def _export_money_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save money CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            write_money(path, self._filtered_entries())
            QtWidgets.QMessageBox.information(self, "Export", "Money entries exported.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))

    def _import_items_csv(self) -> None:
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
            self.main.items = _merge_by_id(self.main.items, imported)
        self.main._sort_items()
        self.main.save_items(trigger_backup=self.main.settings["ui"].get("autosave", True))
        QtWidgets.QMessageBox.information(self, "Import", "Items imported.")

    def _export_items_csv(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save items CSV", filter="CSV Files (*.csv)")
        if not path:
            return
        try:
            write_items(path, self.main.items)
            QtWidgets.QMessageBox.information(self, "Export", "Items exported.")
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", str(exc))

    def _import_bundle(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select bundle", filter="Bundle Files (*.json)")
        if not path:
            return
        try:
            items, money, metadata = read_bundle(path)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Import failed", f"Could not read bundle:\n{exc}")
            return
        details = metadata.get("generated_at", "unknown time") if isinstance(metadata, dict) else "unknown time"
        choice = QtWidgets.QMessageBox.question(
            self,
            "Import Bundle",
            (
                f"Bundle contains {len(items)} items and {len(money)} money entries "
                f"(created {details}).\n\n"
                "Yes = overwrite current items and money with bundle contents.\n"
                "No = append/merge; incoming records replace matching IDs and new IDs are added."
            ),
            QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
        )
        if choice == QtWidgets.QMessageBox.Yes:
            self.main.items = items
            self.main.money = money
        else:
            self.main.items = _merge_by_id(self.main.items, items)
            self.main.money = _merge_by_id(self.main.money, money)
        self.main._sort_items()
        self.main._sort_money()
        autosave = self.main.settings["ui"].get("autosave", True)
        self.main.save_items(trigger_backup=autosave)
        self.main.save_money(trigger_backup=autosave)
        QtWidgets.QMessageBox.information(self, "Import", "Bundle imported.")

    def _export_bundle(self) -> None:
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Save bundle", filter="Bundle Files (*.json)")
        if not path:
            return
        try:
            write_bundle(path, self.main.items, self.main.money)
        except Exception as exc:
            QtWidgets.QMessageBox.critical(self, "Export failed", f"Could not write bundle:\n{exc}")
        else:
            QtWidgets.QMessageBox.information(
                self,
                "Export",
                f"Bundle exported with {len(self.main.items)} items and {len(self.main.money)} money entries.",
            )

    def _clear_filters(self) -> None:
        self.search_edit.clear()
        self.type_filter.setCurrentIndex(0)

    def _handle_sort(self, column: int) -> None:
        if column == self.main.money_sort_column:
            self.main.money_sort_ascending = not self.main.money_sort_ascending
        else:
            self.main.money_sort_column = column
            self.main.money_sort_ascending = True
        self.main._persist_sort_state("money_sort", self.main.money_sort_column, self.main.money_sort_ascending)
        self.main._sort_money()
        self.refresh()


class SettingsWidget(QtWidgets.QWidget):
    def __init__(self, main: MainWindow) -> None:
        super().__init__()
        self.main = main
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QtWidgets.QFormLayout(self)
        layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.autosave_check = QtWidgets.QCheckBox("Enable autosave")
        self.autosave_check.setChecked(self.main.settings["ui"].get("autosave", True))
        self.autosave_check.stateChanged.connect(self._toggle_autosave)
        layout.addRow("Autosave", self.autosave_check)

        backup_btn = QtWidgets.QPushButton("Backup now")
        backup_btn.clicked.connect(self._backup_now)
        open_btn = QtWidgets.QPushButton("Open data folder")
        open_btn.clicked.connect(self._open_data_dir)
        open_cfg_btn = QtWidgets.QPushButton("Open config folder")
        open_cfg_btn.clicked.connect(self._open_config_dir)
        btn_row = QtWidgets.QHBoxLayout()
        btn_row.addWidget(backup_btn)
        btn_row.addWidget(open_btn)
        btn_row.addWidget(open_cfg_btn)
        layout.addRow("Data", btn_row)

        self._add_path_row(layout, "Items file", self.main.items_path)
        self._add_path_row(layout, "Money file", self.main.money_path)
        self._add_path_row(layout, "Backups", self.main.backup_dir)
        self._add_path_row(layout, "Config (settings.json)", self.main.config_manager.settings_path)
        self._add_path_row(layout, "Weights (weights.txt)", self.main.config_manager.weights_path)
        self._add_path_row(layout, "Themes (themes.json)", self.main.config_manager.themes_path)

        info_label = QtWidgets.QLabel(
            "Weights are read-only at runtime. Edit weights.txt in the config folder and restart to apply changes."
        )
        info_label.setWordWrap(True)
        layout.addRow("Weights", info_label)

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

    def _open_config_dir(self) -> None:
        cfg_dir = Path(self.main.config_manager.settings_path).parent
        cfg_dir.mkdir(parents=True, exist_ok=True)
        target = str(cfg_dir)
        if sys.platform.startswith("win"):
            os.startfile(target)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", target])
        else:
            subprocess.Popen(["xdg-open", target])

    def _add_path_row(self, layout: QtWidgets.QFormLayout, label: str, path: str) -> None:
        row = QtWidgets.QHBoxLayout()
        entry = QtWidgets.QLineEdit(path)
        entry.setReadOnly(True)
        copy_btn = QtWidgets.QPushButton("Copy")
        copy_btn.clicked.connect(lambda: QtWidgets.QApplication.clipboard().setText(path))
        row.addWidget(entry)
        row.addWidget(copy_btn)
        layout.addRow(label, row)

    def _add_weights_group(self, layout: QtWidgets.QFormLayout) -> None:
        group = QtWidgets.QGroupBox("Weights (admin)")
        g_layout = QtWidgets.QFormLayout(group)
        g_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        self.weight_spins = {}
        labels = [
            ("Date", "date"),
            ("Cost", "cost"),
            ("Urgency", "urgency"),
            ("Value", "value"),
            ("Want", "want"),
            ("Price vs Similar", "price_comp"),
            ("Effect", "effect"),
        ]
        weights = self.main.weights.get("weights", {})
        for label, key in labels:
            spin = QtWidgets.QDoubleSpinBox()
            spin.setRange(0.0, 10.0)
            spin.setSingleStep(0.1)
            spin.setValue(float(weights.get(key, 1.0)))
            spin.setSuffix("×")
            g_layout.addRow(f"{label} weight", spin)
            self.weight_spins[key] = spin
        save_btn = QtWidgets.QPushButton("Save weights")
        save_btn.clicked.connect(self._save_weights)
        g_layout.addRow(save_btn)
        layout.addRow(group)

    def _save_weights(self) -> None:
        weights_cfg = self.main.weights
        weights_cfg.setdefault("weights", {})
        for key, spin in self.weight_spins.items():
            weights_cfg["weights"][key] = spin.value()
        self.main.apply_weights(weights_cfg)
        QtWidgets.QMessageBox.information(self, "Weights", "Weights saved and applied.")


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
        layout = QtWidgets.QFormLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        self.date_edit = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addRow("Date", self.date_edit)

        self.product = QtWidgets.QLineEdit()
        self.description = QtWidgets.QLineEdit()
        self.location_combo = QtWidgets.QComboBox()
        self.location_options = ["Online", "Brick and Mortar", "Second-hand", "Gift", "Other"]
        self.location_combo.addItems(self.location_options)
        self.location_other = QtWidgets.QLineEdit()
        self.location_other.setPlaceholderText("Specify location")
        self.location_other.setEnabled(False)
        self.location_combo.currentTextChanged.connect(self._location_changed)
        self.reference = QtWidgets.QLineEdit()
        self.cost = QtWidgets.QDoubleSpinBox()
        self.cost.setMaximum(1_000_000)
        self.cost.setPrefix(self.main.currency_symbol)
        self.urgency = QtWidgets.QSpinBox()
        self.urgency.setRange(1, 5)
        self.value = QtWidgets.QSpinBox()
        self.value.setRange(1, 5)
        self.want = QtWidgets.QSpinBox()
        self.want.setRange(1, 5)
        self.want.setValue(3)
        self.price_comp = QtWidgets.QSpinBox()
        self.price_comp.setRange(1, 5)
        self.effect = QtWidgets.QSpinBox()
        self.effect.setRange(1, 5)
        self.justification = QtWidgets.QLineEdit()
        self.recurrence = QtWidgets.QComboBox()
        self.recurrence.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.recurrence.addItems(["none", "once", "weekly", "biweekly", "monthly", "quarterly", "yearly"])

        layout.addRow("Product", self.product)
        layout.addRow("Description", self.description)
        location_row = QtWidgets.QHBoxLayout()
        location_row.setContentsMargins(0, 0, 0, 0)
        location_row.setSpacing(6)
        location_row.addWidget(self.location_combo)
        location_row.addWidget(self.location_other)
        location_container = QtWidgets.QWidget()
        location_container.setLayout(location_row)
        layout.addRow("Location", location_container)
        layout.addRow("Reference", self.reference)
        layout.addRow("Cost", self.cost)
        layout.addRow("Urgency", self.urgency)
        layout.addRow("Value", self.value)
        layout.addRow("Want", self.want)
        layout.addRow("Price vs Similar", self.price_comp)
        layout.addRow("Effect", self.effect)
        layout.addRow("Justification", self.justification)
        layout.addRow("Recurrence", self.recurrence)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

        self._set_tab_order(buttons)

    def _set_tab_order(self, buttons: QtWidgets.QDialogButtonBox) -> None:
        self.setTabOrder(self.date_edit, self.product)
        self.setTabOrder(self.product, self.description)
        self.setTabOrder(self.description, self.location_combo)
        self.setTabOrder(self.location_combo, self.location_other)
        self.setTabOrder(self.location_other, self.reference)
        self.setTabOrder(self.reference, self.cost)
        self.setTabOrder(self.cost, self.urgency)
        self.setTabOrder(self.urgency, self.value)
        self.setTabOrder(self.value, self.want)
        self.setTabOrder(self.want, self.price_comp)
        self.setTabOrder(self.price_comp, self.effect)
        self.setTabOrder(self.effect, self.justification)
        self.setTabOrder(self.justification, self.recurrence)
        save_btn = buttons.button(QtWidgets.QDialogButtonBox.Save)
        cancel_btn = buttons.button(QtWidgets.QDialogButtonBox.Cancel)
        if save_btn:
            self.setTabOrder(self.recurrence, save_btn)
            if cancel_btn:
                self.setTabOrder(save_btn, cancel_btn)
        elif cancel_btn:
            self.setTabOrder(self.recurrence, cancel_btn)

    def _load(self, item: ItemRecord) -> None:
        self.date_edit.setDateTime(QtCore.QDateTime.fromString(item.date.strftime("%Y-%m-%d %H:%M"), "yyyy-MM-dd HH:mm"))
        self.product.setText(item.product)
        self.description.setText(item.description)
        if item.location in self.location_options:
            idx = self.location_combo.findText(item.location)
            if idx >= 0:
                self.location_combo.setCurrentIndex(idx)
            self.location_other.clear()
        else:
            other_idx = self.location_combo.findText("Other")
            if other_idx >= 0:
                self.location_combo.setCurrentIndex(other_idx)
            self.location_other.setText(item.location)
            self.location_other.setEnabled(True)
        self.reference.setText(item.reference)
        self.cost.setValue(item.cost)
        self.urgency.setValue(item.urgency)
        self.value.setValue(item.value)
        self.want.setValue(item.want)
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
        location_choice = self.location_combo.currentText()
        if location_choice == "Other":
            location_value = self.location_other.text().strip() or "Other"
        else:
            location_value = location_choice
        record = ItemRecord(
            id=self.existing.id if self.existing else str(QtCore.QUuid.createUuid()).strip("{}"),
            date=date,
            product=self.product.text(),
            description=self.description.text(),
            location=location_value,
            reference=self.reference.text(),
            cost=float(self.cost.value()),
            urgency=int(self.urgency.value()),
            value=int(self.value.value()),
            want=int(self.want.value()),
            price_comp=int(self.price_comp.value()),
            effect=int(self.effect.value()),
            justification=self.justification.text(),
            recurrence=self.recurrence.currentText(),
        )
        self.result_record = record
        self.accept()

    def _location_changed(self, text: str) -> None:
        self.location_other.setEnabled(text == "Other")


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
        layout = QtWidgets.QFormLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(10, 10, 10, 10)

        self.date_edit = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime())
        self.date_edit.setCalendarPopup(True)
        self.date_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        layout.addRow("Date", self.date_edit)

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

        layout.addRow("Type", self.type_box)
        layout.addRow("Source/Destination", self.source)
        layout.addRow("Amount", self.amount)
        layout.addRow("Notes", self.notes)
        layout.addRow("Linked Item", self.link_combo)

        buttons = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Save | QtWidgets.QDialogButtonBox.Cancel)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

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
    if not sys.platform.startswith("win") or not hasattr(ctypes, "windll"):
        return

    try:
        kernel32 = ctypes.windll.kernel32
        user32 = getattr(ctypes.windll, "user32", None)
        get_console_window = getattr(kernel32, "GetConsoleWindow", None)
        if get_console_window is None:
            return

        hwnd = get_console_window()
        if not hwnd:
            return

        if user32 is not None:
            try:
                SW_HIDE = 0
                user32.ShowWindow(hwnd, SW_HIDE)
            except Exception:
                pass

        try:
            kernel32.FreeConsole()
        except Exception:
            pass
    except Exception:
        pass


def _redirect_stdio_to_null_on_windows() -> None:
    if not sys.platform.startswith("win"):
        return
    try:
        null = open(os.devnull, "w", encoding="utf-8")
        sys.stdout = null  # type: ignore[assignment]
        sys.stderr = null  # type: ignore[assignment]
    except Exception:
        pass
