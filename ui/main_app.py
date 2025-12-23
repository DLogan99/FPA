import calendar
import csv
import os
import subprocess
import sys
import tkinter as tk
from datetime import datetime
from operator import attrgetter
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional
from uuid import uuid4

from core.backup import create_backup
from core.config_manager import ConfigManager, ensure_paths
from core.csv_storage import read_items, read_money, write_items, write_money
from core.models import ItemRecord, MoneyRecord
from scoring.scoring import ScoreResult, score_item


def show_error_dialog(parent: tk.Tk, title: str, message: str, detail: str = "") -> None:
    top = tk.Toplevel(parent)
    top.title(title)
    top.grab_set()
    pad = {"padx": 10, "pady": 6}
    ttk.Label(top, text=message, wraplength=360).grid(row=0, column=0, columnspan=2, sticky="w", **pad)
    if detail:
        text = tk.Text(top, height=6, width=50, wrap="word")
        text.insert("1.0", detail)
        text.config(state="disabled")
        text.grid(row=1, column=0, columnspan=2, sticky="nsew", **pad)

    def _copy():
        top.clipboard_clear()
        top.clipboard_append(detail or message)

    ttk.Button(top, text="Copy error", command=_copy).grid(row=2, column=0, sticky="w", **pad)
    ttk.Button(top, text="Close", command=top.destroy).grid(row=2, column=1, sticky="e", **pad)
    top.columnconfigure(0, weight=1)
    top.columnconfigure(1, weight=1)
    top.rowconfigure(1, weight=1)


class FinancePlannerApp(tk.Tk):
    def __init__(self, config: ConfigManager):
        super().__init__()
        self.title("Finance Planner")
        self.config_manager = config
        ensure_paths(self.config_manager.settings)
        self.settings = self.config_manager.settings
        self.weights = self.config_manager.weights
        self.theme = self.config_manager.get_theme()
        self.items_path = self.settings["paths"]["items_csv"]
        self.money_path = self.settings["paths"]["money_csv"]
        self.backup_dir = self.settings["paths"]["backup_dir"]
        self.date_fmt = self.settings["ui"]["date_format"]
        self.currency_symbol = self.settings["ui"]["currency_symbol"]

        self.style = ttk.Style(self)
        self._apply_theme()

        self.items: List[ItemRecord] = []
        self.money: List[MoneyRecord] = []

        container = ttk.Frame(self, padding=10)
        container.pack(fill="both", expand=True)

        self.notebook = ttk.Notebook(container)
        self.notebook.pack(fill="both", expand=True)

        self.purchases_view = PurchasesView(self, self)
        self.money_view = MoneyView(self, self)
        self.settings_view = SettingsView(self, self)

        self.notebook.add(self.purchases_view, text="Purchases")
        self.notebook.add(self.money_view, text="Money")
        self.notebook.add(self.settings_view, text="Settings")

        self._build_menu()
        self._load_data()
        self.bind_all("<Control-f>", self._focus_search)
        self.bind_all("<Control-e>", self._edit_current)
        self.bind_all("<Control-n>", self._add_current)
        self.bind_all("<F1>", self._show_shortcuts)

    def _apply_theme(self) -> None:
        bg = self.theme.get("background", "#ffffff")
        fg = self.theme.get("foreground", "#000000")
        accent = self.theme.get("accent", "#2563eb")
        table = self.theme.get("table", {})
        row_bg = table.get("row_bg", bg)
        self.configure(bg=bg)
        self.style.theme_use("default")
        self.style.configure("TFrame", background=bg)
        self.style.configure("TLabel", background=bg, foreground=fg)
        self.style.configure("TButton", background=accent, foreground=fg, padding=6)
        self.style.configure("TEntry", fieldbackground=row_bg, foreground=fg, padding=4)
        self.style.configure("Treeview", background=row_bg, foreground=fg, fieldbackground=row_bg, borderwidth=0, relief="flat")
        self.style.configure("TNotebook", background=bg, tabmargins=2)
        self.style.configure("TNotebook.Tab", padding=(10, 6))
        self.style.map("TButton", background=[("active", accent)])
        self.style.configure("HighScore.Treeview", foreground="#16a34a")
        self.style.configure("LowScore.Treeview", foreground="#dc2626")

    def _load_data(self) -> None:
        self.items = read_items(self.items_path)
        self.money = read_money(self.money_path)
        self._sort_items()
        self._sort_money()
        self.purchases_view.refresh_table()
        self.money_view.refresh_table()

    def save_items(self, trigger_backup: bool = True) -> None:
        write_items(self.items_path, self.items)
        if trigger_backup:
            create_backup(self.items_path, self.backup_dir, self.settings["backup"])
        self.purchases_view.refresh_table()

    def save_money(self, trigger_backup: bool = True) -> None:
        write_money(self.money_path, self.money)
        if trigger_backup:
            create_backup(self.money_path, self.backup_dir, self.settings["backup"])
        self.money_view.refresh_table()

    def add_or_edit_item(self, existing: Optional[ItemRecord] = None) -> None:
        dialog = ItemDialog(self, existing)
        self.wait_window(dialog.top)
        if dialog.result:
            record = dialog.result
            scored: ScoreResult = score_item(record, self.weights)
            record.overall_score = scored.overall
            if existing:
                self.items = [record if i.id == existing.id else i for i in self.items]
            else:
                self.items.append(record)
            self._sort_items()
            self.save_items(trigger_backup=self.settings["ui"].get("autosave", True))

    def view_item(self, record: ItemRecord) -> None:
        ItemViewer(self, record)

    def add_money_entry(self, existing: Optional[MoneyRecord] = None) -> None:
        dialog = MoneyDialog(self, existing, self.items)
        self.wait_window(dialog.top)
        if dialog.result:
            record = dialog.result
            if existing:
                self.money = [record if m.id == existing.id else m for m in self.money]
            else:
                self.money.append(record)
            self._sort_money()
            self.save_money(trigger_backup=self.settings["ui"].get("autosave", True))

    def change_theme(self, name: str) -> None:
        self.theme = self.config_manager.get_theme(name)
        self.config_manager.set_default_theme(name)
        self._apply_theme()
        self.purchases_view.refresh_table()
        self.money_view.refresh_table()
        self.settings_view.refresh_theme_dropdown()

    def _focus_search(self, event=None) -> None:
        current = self.notebook.select()
        if current == str(self.purchases_view):
            self.purchases_view.search_entry.focus_set()
        elif current == str(self.money_view):
            self.money_view.search_entry.focus_set()

    def _edit_current(self, event=None) -> None:
        current = self.notebook.select()
        if current == str(self.purchases_view):
            self.purchases_view.edit_selected()
        elif current == str(self.money_view):
            self.money_view.edit_selected()

    def _add_current(self, event=None) -> None:
        current = self.notebook.select()
        if current == str(self.purchases_view):
            self.purchases_view.add_new()
        elif current == str(self.money_view):
            self.money_view.add_new()

    def _sort_items(self) -> None:
        self.items.sort(key=attrgetter("date"), reverse=True)

    def _sort_money(self) -> None:
        self.money.sort(key=attrgetter("date"), reverse=True)

    def _build_menu(self) -> None:
        menubar = tk.Menu(self)
        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="Keyboard shortcuts (F1)", command=self._show_shortcuts, accelerator="F1")
        menubar.add_cascade(label="Help", menu=help_menu)
        self.config(menu=menubar)

    def _show_shortcuts(self, event=None) -> None:
        top = tk.Toplevel(self)
        top.title("Keyboard shortcuts")
        top.grab_set()
        pad = {"padx": 10, "pady": 6}
        shortcuts = [
            ("Ctrl+F", "Focus search in current tab"),
            ("Ctrl+N", "Add item/entry in current tab"),
            ("Ctrl+E", "Edit selected row in current tab"),
            ("Enter", "Edit selected row"),
            ("Delete", "Delete selected row"),
            ("Double-click", "Edit selected row"),
        ]
        ttk.Label(top, text="Keyboard & Mouse Shortcuts", font=("TkDefaultFont", 11, "bold")).grid(
            row=0, column=0, sticky="w", **pad
        )
        for idx, (keys, desc) in enumerate(shortcuts, start=1):
            ttk.Label(top, text=keys).grid(row=idx, column=0, sticky="w", **pad)
            ttk.Label(top, text=desc).grid(row=idx, column=1, sticky="w", **pad)
        ttk.Button(top, text="Close", command=top.destroy).grid(row=len(shortcuts) + 1, column=1, sticky="e", **pad)
        top.columnconfigure(1, weight=1)


class PurchasesView(ttk.Frame):
    def __init__(self, parent, app: FinancePlannerApp):
        super().__init__(parent)
        self.app = app
        self.search_var = tk.StringVar(value="")
        self.score_filter_var = tk.StringVar(value="all")
        self.total_cost_var = tk.StringVar(value=f"{self.app.currency_symbol}0.00")
        self.avg_score_var = tk.StringVar(value="0.00")
        self.count_var = tk.StringVar(value="0 items")
        self._build_ui()

    def _build_ui(self) -> None:
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=6)
        ttk.Button(btn_frame, text="Add Item", command=self._add_item).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Edit Selected", command=self._edit_item).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="View Selected", command=self._view_item).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Delete Selected", command=self._delete_item).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Refresh", command=self.refresh_table).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Import CSV", command=self._import_csv).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Export CSV", command=self._export_csv).pack(side="left", padx=4)

        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(search_frame, text="Search").pack(side="left")
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.search_entry.bind("<KeyRelease>", self._on_search)
        ttk.Button(search_frame, text="Clear", command=self._clear_search).pack(side="left", padx=(6, 0))
        ttk.Label(search_frame, text="Score filter").pack(side="left", padx=(8, 2))
        ttk.Combobox(
            search_frame,
            textvariable=self.score_filter_var,
            values=["all", "high (>4)", "low (<2.5)"],
            state="readonly",
            width=10,
        ).pack(side="left")
        self.score_filter_var.trace_add("write", lambda *_: self.refresh_table())

        columns = ("product", "date", "cost", "urgency", "overall")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        headings = ["Product", "Date", "Cost", "Urgency", "Overall"]
        for col, text in zip(columns, headings):
            self.tree.heading(col, text=text, command=lambda c=col: self._sort_by(c, False))
            self.tree.column(col, width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.bind("<Delete>", self._on_delete_key)
        self.tree.bind("<Return>", self._on_row_double_click)

        summary = ttk.Frame(self)
        summary.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(summary, text="Total Cost:").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.total_cost_var).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(summary, text="Average Score:").grid(row=0, column=2, sticky="w")
        ttk.Label(summary, textvariable=self.avg_score_var).grid(row=0, column=3, sticky="w", padx=(4, 0))
        ttk.Label(summary, textvariable=self.count_var, anchor="e").grid(row=0, column=4, sticky="e")
        summary.columnconfigure(4, weight=1)

    def refresh_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        filtered = self._filtered_items()
        total_cost = 0.0
        scored_items = 0
        score_sum = 0.0
        count = 0
        for item in filtered:
            tag = ""
            if (item.overall_score or 0) > 4:
                tag = "high"
            elif (item.overall_score or 0) < 2.5:
                tag = "low"
            self.tree.insert(
                "",
                "end",
                iid=item.id,
                tags=(tag,) if tag else (),
                values=(
                    item.product,
                    item.date.strftime(self.app.date_fmt),
                    f"{self.app.currency_symbol}{item.cost:.2f}",
                    item.urgency,
                    f"{(item.overall_score or 0):.2f}",
                ),
            )
            total_cost += item.cost
            if item.overall_score is not None:
                scored_items += 1
                score_sum += item.overall_score
            count += 1
        self.tree.tag_configure("high", foreground="#16a34a")
        self.tree.tag_configure("low", foreground="#dc2626")
        avg = score_sum / scored_items if scored_items else 0.0
        self.total_cost_var.set(f"{self.app.currency_symbol}{total_cost:.2f}")
        self.avg_score_var.set(f"{avg:.2f}")
        self.count_var.set(f"{count} item{'s' if count != 1 else ''}")

    def _get_selected_item(self) -> Optional[ItemRecord]:
        selected = self.tree.selection()
        if not selected:
            return None
        item_id = selected[0]
        for item in self.app.items:
            if item.id == item_id:
                return item
        return None

    def _sort_by(self, col: str, descending: bool) -> None:
        data = []
        for item_id in self.tree.get_children(""):
            values = self.tree.item(item_id)["values"]
            col_index = {"product": 0, "date": 1, "cost": 2, "urgency": 3, "overall": 4}[col]
            data.append((values[col_index], item_id))

        def cast(val):
            if col in ("cost", "urgency", "overall"):
                try:
                    return float(val.strip("$")) if isinstance(val, str) else float(val)
                except Exception:
                    return 0
            if col == "date":
                try:
                    return datetime.strptime(val, self.app.date_fmt)
                except Exception:
                    return datetime.min
            return str(val).lower()

        data.sort(key=lambda t: cast(t[0]), reverse=descending)
        for idx, (_, iid) in enumerate(data):
            self.tree.move(iid, "", idx)
        self.tree.heading(col, command=lambda c=col: self._sort_by(c, not descending))

    def _add_item(self) -> None:
        self.app.add_or_edit_item()

    def add_new(self) -> None:
        self._add_item()

    def _edit_item(self) -> None:
        record = self._get_selected_item()
        if not record:
            messagebox.showinfo("Edit Item", "Select a row to edit.")
            return
        self.app.add_or_edit_item(record)

    def edit_selected(self) -> None:
        self._edit_item()

    def _view_item(self) -> None:
        record = self._get_selected_item()
        if not record:
            messagebox.showinfo("View Item", "Select a row to view.")
            return
        self.app.view_item(record)

    def _delete_item(self) -> None:
        record = self._get_selected_item()
        if not record:
            messagebox.showinfo("Delete Item", "Select a row to delete.")
            return
        if not messagebox.askyesno("Delete Item", f"Delete '{record.product}'?"):
            return
        self.app.items = [i for i in self.app.items if i.id != record.id]
        self.app.save_items(trigger_backup=self.app.settings["ui"].get("autosave", True))

    def delete_selected(self) -> None:
        self._delete_item()

    def _import_csv(self) -> None:
        try:
            path = filedialog.askopenfilename(
                title="Select items CSV",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            )
        except Exception as exc:
            show_error_dialog(self, "Import", "Failed to open file dialog.", str(exc))
            return
        if not path:
            return
        try:
            imported = read_items(path)
        except Exception as exc:
            show_error_dialog(self, "Import", "Failed to read CSV.", str(exc))
            return
        choice = messagebox.askyesnocancel(
            "Import Items",
            "Replace existing items with imported data?\n\nYes = replace, No = append, Cancel = abort.",
        )
        if choice is None:
            return
        if choice:
            self.app.items = imported
        else:
            merged = {item.id: item for item in self.app.items}
            for item in imported:
                merged[item.id] = item
            self.app.items = list(merged.values())
        self.app._sort_items()
        self.app.save_items(trigger_backup=self.app.settings["ui"].get("autosave", True))
        messagebox.showinfo("Import", "Items imported.")

    def _filtered_items(self) -> List[ItemRecord]:
        query = self.search_var.get().strip().lower()
        if not query:
            filtered = list(self.app.items)
        else:
            filtered = []
            for item in self.app.items:
                haystack = " ".join(
                    [
                        item.product,
                        item.description,
                        item.location,
                        item.reference,
                        item.justification,
                    ]
                ).lower()
                if query in haystack:
                    filtered.append(item)
        filter_mode = self.score_filter_var.get()
        if filter_mode.startswith("high"):
            filtered = [i for i in filtered if (i.overall_score or 0) > 4]
        elif filter_mode.startswith("low"):
            filtered = [i for i in filtered if (i.overall_score or 0) < 2.5]
        result = []
        seen = set()
        for item in filtered:
            if item.id not in seen:
                seen.add(item.id)
                result.append(item)
        return result

    def _on_search(self, event=None) -> None:
        self.refresh_table()

    def _clear_search(self) -> None:
        if self.search_var.get():
            self.search_var.set("")
            self.refresh_table()

    def _on_row_double_click(self, event) -> None:
        record = self._get_selected_item()
        if record:
            self.app.add_or_edit_item(record)

    def _on_delete_key(self, event) -> None:
        self._delete_item()

    def _export_csv(self) -> None:
        try:
            path = filedialog.asksaveasfilename(
                title="Save purchases CSV",
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            )
        except Exception as exc:
            show_error_dialog(self, "Export", "Failed to open save dialog.", str(exc))
            return
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=ItemRecord.headers())
                writer.writeheader()
                for item in self._filtered_items():
                    writer.writerow(item.to_row(self.app.date_fmt))
            messagebox.showinfo("Export", "Purchases exported.")
        except Exception as exc:
            show_error_dialog(self, "Export", "Failed to export purchases.", str(exc))


class MoneyView(ttk.Frame):
    def __init__(self, parent, app: FinancePlannerApp):
        super().__init__(parent)
        self.app = app
        self.search_var = tk.StringVar(value="")
        self.income_var = tk.StringVar(value=f"{self.app.currency_symbol}0.00")
        self.expense_var = tk.StringVar(value=f"{self.app.currency_symbol}0.00")
        self.balance_var = tk.StringVar(value=f"{self.app.currency_symbol}0.00")
        self.count_var = tk.StringVar(value="0 entries")
        self.type_filter_var = tk.StringVar(value="all")
        self._build_ui()

    def _build_ui(self) -> None:
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=6)
        ttk.Button(btn_frame, text="Add Entry", command=self._add_entry).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Edit Selected", command=self._edit_entry).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Delete Selected", command=self._delete_entry).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Refresh", command=self.refresh_table).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Import CSV", command=self._import_csv).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Export CSV", command=self._export_csv).pack(side="left", padx=4)

        search_frame = ttk.Frame(self)
        search_frame.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(search_frame, text="Search").pack(side="left")
        self.search_entry = ttk.Entry(search_frame, textvariable=self.search_var)
        self.search_entry.pack(side="left", fill="x", expand=True, padx=(6, 0))
        self.search_entry.bind("<KeyRelease>", self._on_search)
        ttk.Button(search_frame, text="Clear", command=self._clear_search).pack(side="left", padx=(6, 0))
        ttk.Label(search_frame, text="Type").pack(side="left", padx=(8, 2))
        ttk.Combobox(
            search_frame,
            textvariable=self.type_filter_var,
            values=["all", "income", "expense"],
            state="readonly",
            width=10,
        ).pack(side="left")
        self.type_filter_var.trace_add("write", lambda *_: self.refresh_table())

        columns = ("date", "type", "source", "amount", "linked_item")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        headings = ["Date", "Type", "Source/Destination", "Amount", "Linked Item"]
        for col, text in zip(columns, headings):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=140, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)
        self.tree.bind("<Double-1>", self._on_row_double_click)
        self.tree.bind("<Delete>", self._on_delete_key)
        self.tree.bind("<Return>", self._on_row_double_click)

        summary = ttk.Frame(self)
        summary.pack(fill="x", padx=8, pady=(0, 6))
        ttk.Label(summary, text="Income:").grid(row=0, column=0, sticky="w")
        ttk.Label(summary, textvariable=self.income_var).grid(row=0, column=1, sticky="w", padx=(4, 12))
        ttk.Label(summary, text="Expenses:").grid(row=0, column=2, sticky="w")
        ttk.Label(summary, textvariable=self.expense_var).grid(row=0, column=3, sticky="w", padx=(4, 12))
        ttk.Label(summary, text="Balance:").grid(row=0, column=4, sticky="w")
        ttk.Label(summary, textvariable=self.balance_var, font=("TkDefaultFont", 10, "bold")).grid(
            row=0, column=5, sticky="w", padx=(4, 0)
        )
        ttk.Label(summary, textvariable=self.count_var, anchor="e").grid(row=0, column=6, sticky="e")
        summary.columnconfigure(6, weight=1)

    def refresh_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        id_to_product = {item.id: item.product for item in self.app.items}
        income = 0.0
        expense = 0.0
        count = 0
        for entry in self._filtered_entries():
            linked_display = id_to_product.get(entry.linked_item_id, entry.linked_item_id)
            entry_type = entry.entry_type.lower()
            if entry_type == "income":
                income += entry.amount
            elif entry_type == "expense":
                expense += entry.amount
            self.tree.insert(
                "",
                "end",
                iid=entry.id,
                values=(
                    entry.date.strftime(self.app.date_fmt),
                    entry.entry_type.title(),
                    entry.source_or_destination,
                    f"{self.app.currency_symbol}{entry.amount:.2f}",
                    linked_display,
                ),
            )
            count += 1
        self._update_summary(income, expense)
        self.count_var.set(f"{count} {'entry' if count == 1 else 'entries'}")

    def _get_selected_entry(self) -> Optional[MoneyRecord]:
        selected = self.tree.selection()
        if not selected:
            return None
        entry_id = selected[0]
        for entry in self.app.money:
            if entry.id == entry_id:
                return entry
        return None

    def _add_entry(self) -> None:
        self.app.add_money_entry()

    def add_new(self) -> None:
        self._add_entry()

    def _edit_entry(self) -> None:
        record = self._get_selected_entry()
        if not record:
            messagebox.showinfo("Edit Entry", "Select a row to edit.")
            return
        self.app.add_money_entry(record)

    def edit_selected(self) -> None:
        self._edit_entry()

    def _delete_entry(self) -> None:
        record = self._get_selected_entry()
        if not record:
            messagebox.showinfo("Delete Entry", "Select a row to delete.")
            return
        if not messagebox.askyesno("Delete Entry", "Delete this entry?"):
            return
        self.app.money = [m for m in self.app.money if m.id != record.id]
        self.app.save_money(trigger_backup=self.app.settings["ui"].get("autosave", True))

    def delete_selected(self) -> None:
        self._delete_entry()

    def _update_summary(self, income: float, expense: float) -> None:
        balance = income - expense
        self.income_var.set(f"{self.app.currency_symbol}{income:.2f}")
        self.expense_var.set(f"{self.app.currency_symbol}{expense:.2f}")
        self.balance_var.set(f"{self.app.currency_symbol}{balance:.2f}")

    def _filtered_entries(self) -> List[MoneyRecord]:
        query = self.search_var.get().strip().lower()
        if not query:
            candidates = list(self.app.money)
        else:
            id_to_product = {item.id: item.product for item in self.app.items}
            candidates = []
            for entry in self.app.money:
                linked_product = id_to_product.get(entry.linked_item_id, "")
                fields = " ".join(
                    [
                        entry.entry_type,
                        entry.source_or_destination,
                        entry.notes,
                        entry.linked_item_id,
                        linked_product,
                    ]
                ).lower()
                if query in fields:
                    candidates.append(entry)
        filter_type = self.type_filter_var.get().lower()
        if filter_type in {"income", "expense"}:
            candidates = [e for e in candidates if e.entry_type.lower() == filter_type]
        id_to_product = {item.id: item.product for item in self.app.items}
        deduped = []
        seen = set()
        for entry in candidates:
            if entry.id in seen:
                continue
            seen.add(entry.id)
            deduped.append(entry)
        return deduped

    def _on_search(self, event=None) -> None:
        self.refresh_table()

    def _clear_search(self) -> None:
        if self.search_var.get():
            self.search_var.set("")
            self.refresh_table()

    def _on_row_double_click(self, event) -> None:
        record = self._get_selected_entry()
        if record:
            self.app.add_money_entry(record)

    def _on_delete_key(self, event) -> None:
        self._delete_entry()

    def _import_csv(self) -> None:
        try:
            path = filedialog.askopenfilename(
                title="Select money CSV",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            )
        except Exception as exc:
            show_error_dialog(self, "Import", "Failed to open file dialog.", str(exc))
            return
        if not path:
            return
        try:
            imported = read_money(path)
        except Exception as exc:
            show_error_dialog(self, "Import", "Failed to read CSV.", str(exc))
            return
        choice = messagebox.askyesnocancel(
            "Import Money",
            "Replace existing entries with imported data?\n\nYes = replace, No = append, Cancel = abort.",
        )
        if choice is None:
            return
        if choice:
            self.app.money = imported
        else:
            merged = {entry.id: entry for entry in self.app.money}
            for entry in imported:
                merged[entry.id] = entry
            self.app.money = list(merged.values())
        self.app._sort_money()
        self.app.save_money(trigger_backup=self.app.settings["ui"].get("autosave", True))
        messagebox.showinfo("Import", "Money entries imported.")

    def _export_csv(self) -> None:
        try:
            path = filedialog.asksaveasfilename(
                title="Save money CSV",
                defaultextension=".csv",
                filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")],
            )
        except Exception as exc:
            show_error_dialog(self, "Export", "Failed to open save dialog.", str(exc))
            return
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.DictWriter(fh, fieldnames=MoneyRecord.headers())
                writer.writeheader()
                for entry in self._filtered_entries():
                    writer.writerow(entry.to_row(self.app.date_fmt))
            messagebox.showinfo("Export", "Money entries exported.")
        except Exception as exc:
            show_error_dialog(self, "Export", "Failed to export money entries.", str(exc))


class SettingsView(ttk.Frame):
    def __init__(self, parent, app: FinancePlannerApp):
        super().__init__(parent)
        self.app = app
        self.theme_var = tk.StringVar(value=self.app.config_manager.settings["themes"]["default"])
        self._build_ui()

    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}
        ttk.Label(self, text="Default Theme").grid(row=0, column=0, sticky="w", **pad)
        self.theme_menu = ttk.Combobox(self, textvariable=self.theme_var, state="readonly")
        self.refresh_theme_dropdown()
        self.theme_menu.grid(row=0, column=1, sticky="ew", **pad)
        self.theme_menu.bind("<<ComboboxSelected>>", self._apply_theme)

        ttk.Label(self, text="Autosave").grid(row=1, column=0, sticky="w", **pad)
        self.autosave_var = tk.BooleanVar(value=self.app.settings["ui"].get("autosave", True))
        ttk.Checkbutton(self, variable=self.autosave_var, command=self._toggle_autosave).grid(row=1, column=1, sticky="w", **pad)

        ttk.Button(self, text="Backup Now", command=self._backup_now).grid(row=2, column=0, **pad)
        ttk.Button(self, text="Open data folder", command=self._open_data_dir).grid(row=2, column=1, sticky="w", **pad)

        ttk.Label(self, text="Items file").grid(row=3, column=0, sticky="w", **pad)
        self._make_path_row(row=3, path=self.app.items_path, pad=pad, copy_label="Copy items")
        ttk.Label(self, text="Money file").grid(row=4, column=0, sticky="w", **pad)
        self._make_path_row(row=4, path=self.app.money_path, pad=pad, copy_label="Copy money")
        ttk.Label(self, text="Backup folder").grid(row=5, column=0, sticky="w", **pad)
        self._make_path_row(row=5, path=self.app.backup_dir, pad=pad, copy_label="Copy backups")

        self.columnconfigure(1, weight=1)

    def refresh_theme_dropdown(self) -> None:
        self.theme_menu["values"] = list(self.app.config_manager.themes.keys())
        self.theme_menu.set(self.app.config_manager.settings["themes"]["default"])

    def _apply_theme(self, event=None) -> None:
        name = self.theme_var.get()
        self.app.change_theme(name)

    def _toggle_autosave(self) -> None:
        self.app.settings["ui"]["autosave"] = self.autosave_var.get()
        self.app.config_manager.save_settings()

    def _backup_now(self) -> None:
        try:
            create_backup(self.app.items_path, self.app.backup_dir, self.app.settings["backup"])
            create_backup(self.app.money_path, self.app.backup_dir, self.app.settings["backup"])
            messagebox.showinfo("Backup", "Backups created.")
        except FileNotFoundError as exc:
            show_error_dialog(self, "Backup", "Backup failed.", str(exc))

    def _open_data_dir(self) -> None:
        paths = {
            "items": os.path.dirname(self.app.items_path),
            "money": os.path.dirname(self.app.money_path),
            "backup": self.app.backup_dir,
        }
        target = None
        for path in paths.values():
            if path:
                try:
                    os.makedirs(path, exist_ok=True)
                    target = path
                    break
                except OSError:
                    continue
        if not target or not os.path.exists(target):
            messagebox.showinfo("Open folder", "Data folder not found yet. Save data first.")
            return
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.check_call(["open", target])
            else:
                subprocess.check_call(["xdg-open", target])
        except Exception as exc:
            show_error_dialog(self, "Open folder", "Unable to open data folder.", str(exc))

    def _make_path_row(self, row: int, path: str, pad: Dict[str, int], copy_label: str = "Copy") -> None:
        frame = ttk.Frame(self)
        frame.grid(row=row, column=1, sticky="ew", **pad)
        label = ttk.Entry(frame)
        label.insert(0, path)
        label.config(state="readonly")
        label.pack(side="left", fill="x", expand=True)
        ttk.Button(frame, text=copy_label, command=lambda p=path: self._copy_path(p)).pack(side="left", padx=4)
        frame.columnconfigure(0, weight=1)

    def _copy_path(self, path: str) -> None:
        try:
            self.clipboard_clear()
            self.clipboard_append(path)
        except Exception as exc:
            show_error_dialog(self, "Copy", "Failed to copy path.", str(exc))


class DatePickerDialog:
    @staticmethod
    def pick(parent: tk.Tk, current_value: str, date_fmt: str) -> Optional[datetime]:
        try:
            current = datetime.strptime(current_value, date_fmt)
        except Exception:
            current = datetime.now()
        dialog = DatePickerDialog(parent, current)
        parent.wait_window(dialog.top)
        return dialog.result

    def __init__(self, parent: tk.Tk, initial: datetime):
        self.result: Optional[datetime] = None
        self.top = tk.Toplevel(parent)
        self.top.title("Pick a date")
        self.top.grab_set()
        self.top.configure(padx=6, pady=6)
        self.current = initial
        self._build_ui()
        self._render_days()

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}
        header = ttk.Frame(self.top)
        header.pack(fill="x", **pad)
        ttk.Button(header, text="◀", width=3, command=self._prev_month).pack(side="left")
        self.month_label = ttk.Label(header, text="", width=20, anchor="center")
        self.month_label.pack(side="left", expand=True)
        ttk.Button(header, text="▶", width=3, command=self._next_month).pack(side="left")

        self.days_frame = ttk.Frame(self.top)
        self.days_frame.pack(fill="both", expand=True, **pad)

        ttk.Button(self.top, text="Today", command=self._set_today).pack(side="left", padx=pad["padx"], pady=pad["pady"])
        ttk.Button(self.top, text="Close", command=self.top.destroy).pack(side="right", padx=pad["padx"], pady=pad["pady"])

    def _render_days(self) -> None:
        for widget in self.days_frame.winfo_children():
            widget.destroy()
        self.month_label.config(text=self.current.strftime("%B %Y"))
        days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
        for idx, name in enumerate(days):
            ttk.Label(self.days_frame, text=name, anchor="center").grid(row=0, column=idx, padx=2, pady=2)
        month_calendar = calendar.Calendar(firstweekday=0).monthdatescalendar(self.current.year, self.current.month)
        for r, week in enumerate(month_calendar, start=1):
            for c, day in enumerate(week):
                btn = ttk.Button(
                    self.days_frame,
                    text=str(day.day),
                    width=4,
                    command=lambda d=day: self._choose(d),
                )
                state = "normal" if day.month == self.current.month else "disabled"
                btn.state([state] if state != "normal" else [])
                btn.grid(row=r, column=c, padx=1, pady=1)

    def _choose(self, day: datetime.date) -> None:
        self.result = datetime.combine(day, datetime.min.time())
        self.top.destroy()

    def _prev_month(self) -> None:
        year = self.current.year
        month = self.current.month - 1
        if month == 0:
            month = 12
            year -= 1
        self.current = self.current.replace(year=year, month=month, day=1)
        self._render_days()

    def _next_month(self) -> None:
        year = self.current.year
        month = self.current.month + 1
        if month == 13:
            month = 1
            year += 1
        self.current = self.current.replace(year=year, month=month, day=1)
        self._render_days()

    def _set_today(self) -> None:
        self.result = datetime.now()
        self.top.destroy()


class ItemDialog:
    def __init__(self, app: FinancePlannerApp, existing: Optional[ItemRecord] = None):
        self.app = app
        self.top = tk.Toplevel(app)
        self.top.title("Item" if not existing else "Edit Item")
        self.top.grab_set()
        self.top.configure(padx=6, pady=6)
        self.result: Optional[ItemRecord] = None
        self.existing = existing
        self._build_ui()
        if existing:
            self._load(existing)

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}
        self.entries: Dict[str, tk.Entry] = {}
        fields = [
            ("Product", "product"),
            ("Description", "description"),
            ("Location", "location"),
            ("Reference", "reference"),
            ("Cost", "cost"),
            ("Urgency (1-5)", "urgency"),
            ("Value (1-5)", "value"),
            ("Price vs Similar (1-5)", "price_comp"),
            ("Effect (1-5)", "effect"),
            ("Justification", "justification"),
        ]
        self.date_var = tk.StringVar(value=datetime.now().strftime(self.app.date_fmt))
        ttk.Label(self.top, text="Date").grid(row=0, column=0, sticky="w", **pad)
        date_row = ttk.Frame(self.top)
        date_row.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Entry(date_row, textvariable=self.date_var).pack(side="left", fill="x", expand=True)
        ttk.Button(date_row, text="Pick", command=self._pick_date).pack(side="left", padx=(6, 0))

        row = 1
        for label, key in fields:
            ttk.Label(self.top, text=label).grid(row=row, column=0, sticky="w", **pad)
            entry = ttk.Entry(self.top)
            entry.grid(row=row, column=1, sticky="ew", **pad)
            self.entries[key] = entry
            row += 1

        ttk.Label(self.top, text="Recurrence").grid(row=row, column=0, sticky="w", **pad)
        self.recurrence_var = tk.StringVar(value="none")
        recurrence_options = [
            "none",
            "once",
            "weekly",
            "biweekly",
            "monthly",
            "quarterly",
            "yearly",
            "custom-date",
        ]
        self.recurrence_combo = ttk.Combobox(
            self.top,
            textvariable=self.recurrence_var,
            values=recurrence_options,
            state="readonly",
        )
        self.recurrence_combo.grid(row=row, column=1, sticky="ew", **pad)
        self.recurrence_combo.bind("<<ComboboxSelected>>", self._maybe_prompt_custom_date)

        ttk.Button(self.top, text="Save", command=self._save).grid(row=row, column=0, columnspan=2, pady=8)
        self.top.columnconfigure(1, weight=1)

    def _load(self, item: ItemRecord) -> None:
        self.date_var.set(item.date.strftime(self.app.date_fmt))
        self.entries["product"].insert(0, item.product)
        self.entries["description"].insert(0, item.description)
        self.entries["location"].insert(0, item.location)
        self.entries["reference"].insert(0, item.reference)
        self.entries["cost"].insert(0, str(item.cost))
        self.entries["urgency"].insert(0, str(item.urgency))
        self.entries["value"].insert(0, str(item.value))
        self.entries["price_comp"].insert(0, str(item.price_comp))
        self.entries["effect"].insert(0, str(item.effect))
        self.entries["justification"].insert(0, item.justification)
        if item.recurrence:
            self.recurrence_var.set(item.recurrence)
        else:
            self.recurrence_var.set("none")

    def _save(self) -> None:
        try:
            date = datetime.strptime(self.date_var.get(), self.app.date_fmt)
            cost = float(self.entries["cost"].get() or 0)
            urgency = int(self.entries["urgency"].get() or 1)
            value = int(self.entries["value"].get() or 1)
            price_comp = int(self.entries["price_comp"].get() or 1)
            effect = int(self.entries["effect"].get() or 1)
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        record = ItemRecord(
            id=self.existing.id if self.existing else str(uuid4()),
            date=date,
            product=self.entries["product"].get(),
            description=self.entries["description"].get(),
            location=self.entries["location"].get(),
            reference=self.entries["reference"].get(),
            cost=cost,
            urgency=urgency,
            value=value,
            price_comp=price_comp,
            effect=effect,
            justification=self.entries["justification"].get(),
            recurrence=self.recurrence_var.get(),
        )
        self.result = record
        self.top.destroy()

    def _maybe_prompt_custom_date(self, event=None):
        if self.recurrence_var.get() != "custom-date":
            return
        prompt = "Enter custom recurrence date (YYYY-MM-DD):"
        value = simpledialog.askstring("Custom date", prompt, parent=self.top)
        if value:
            self.recurrence_var.set(value)
        else:
            self.recurrence_var.set("none")

    def _pick_date(self) -> None:
        selected = DatePickerDialog.pick(self.top, self.date_var.get(), self.app.date_fmt)
        if selected:
            self.date_var.set(selected.strftime(self.app.date_fmt))


class ItemViewer:
    def __init__(self, app: FinancePlannerApp, record: ItemRecord):
        top = tk.Toplevel(app)
        top.title("View Item")
        pad = {"padx": 8, "pady": 4}
        fields = {
            "Product": record.product,
            "Date": record.date.strftime(app.date_fmt),
            "Cost": f"{app.currency_symbol}{record.cost:.2f}",
            "Urgency": record.urgency,
            "Value": record.value,
            "Price vs Similar": record.price_comp,
            "Effect": record.effect,
            "Justification": record.justification,
            "Reference": record.reference,
            "Location": record.location,
            "Recurrence": record.recurrence,
            "Overall Score": f"{(record.overall_score or 0):.2f}",
        }
        row = 0
        for label, value in fields.items():
            ttk.Label(top, text=label).grid(row=row, column=0, sticky="w", **pad)
            ttk.Label(top, text=str(value)).grid(row=row, column=1, sticky="w", **pad)
            row += 1


class MoneyDialog:
    def __init__(self, app: FinancePlannerApp, existing: Optional[MoneyRecord], items: List[ItemRecord]):
        self.app = app
        self.items = items
        self.top = tk.Toplevel(app)
        self.top.title("Money Entry" if not existing else "Edit Money Entry")
        self.top.grab_set()
        self.top.configure(padx=6, pady=6)
        self.result: Optional[MoneyRecord] = None
        self.existing = existing
        self._build_ui()
        if existing:
            self._load(existing)

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}
        self.date_var = tk.StringVar(value=datetime.now().strftime(self.app.date_fmt))
        ttk.Label(self.top, text="Date").grid(row=0, column=0, sticky="w", **pad)
        date_row = ttk.Frame(self.top)
        date_row.grid(row=0, column=1, sticky="ew", **pad)
        ttk.Entry(date_row, textvariable=self.date_var).pack(side="left", fill="x", expand=True)
        ttk.Button(date_row, text="Pick", command=self._pick_date).pack(side="left", padx=(6, 0))

        ttk.Label(self.top, text="Type").grid(row=1, column=0, sticky="w", **pad)
        self.type_var = tk.StringVar(value="income")
        ttk.Combobox(self.top, textvariable=self.type_var, values=["income", "expense"], state="readonly").grid(
            row=1, column=1, sticky="ew", **pad
        )

        ttk.Label(self.top, text="Source/Destination").grid(row=2, column=0, sticky="w", **pad)
        self.source_entry = ttk.Entry(self.top)
        self.source_entry.grid(row=2, column=1, sticky="ew", **pad)

        ttk.Label(self.top, text="Amount").grid(row=3, column=0, sticky="w", **pad)
        self.amount_entry = ttk.Entry(self.top)
        self.amount_entry.grid(row=3, column=1, sticky="ew", **pad)

        ttk.Label(self.top, text="Notes").grid(row=4, column=0, sticky="w", **pad)
        self.notes_entry = ttk.Entry(self.top)
        self.notes_entry.grid(row=4, column=1, sticky="ew", **pad)

        ttk.Label(self.top, text="Linked Item ID (optional)").grid(row=5, column=0, sticky="w", **pad)
        self.link_var = tk.StringVar(value="")
        self.link_map = {"": ""}
        options = []
        for item in self.items:
            display = f"{item.product} ({item.id})"
            self.link_map[display] = item.id
            options.append(display)
        ttk.Combobox(
            self.top,
            textvariable=self.link_var,
            values=[""] + options,
            state="readonly",
        ).grid(row=5, column=1, sticky="ew", **pad)

        ttk.Button(self.top, text="Save", command=self._save).grid(row=6, column=0, columnspan=2, pady=8)
        self.top.columnconfigure(1, weight=1)

    def _load(self, entry: MoneyRecord) -> None:
        self.date_var.set(entry.date.strftime(self.app.date_fmt))
        self.type_var.set(entry.entry_type)
        self.source_entry.insert(0, entry.source_or_destination)
        self.amount_entry.insert(0, str(entry.amount))
        self.notes_entry.insert(0, entry.notes)
        display = next((k for k, v in self.link_map.items() if v == entry.linked_item_id), "")
        self.link_var.set(display)

    def _save(self) -> None:
        try:
            date = datetime.strptime(self.date_var.get(), self.app.date_fmt)
            amount = float(self.amount_entry.get() or 0)
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc))
            return

        record = MoneyRecord(
            id=self.existing.id if self.existing else str(uuid4()),
            date=date,
            entry_type=self.type_var.get().strip().lower() or "income",
            source_or_destination=self.source_entry.get(),
            amount=amount,
            notes=self.notes_entry.get(),
            linked_item_id=self.link_map.get(self.link_var.get(), ""),
        )
        self.result = record
        self.top.destroy()

    def _pick_date(self) -> None:
        selected = DatePickerDialog.pick(self.top, self.date_var.get(), self.app.date_fmt)
        if selected:
            self.date_var.set(selected.strftime(self.app.date_fmt))


def launch() -> None:
    config = ConfigManager()
    app = FinancePlannerApp(config)
    app.mainloop()


if __name__ == "__main__":
    launch()
