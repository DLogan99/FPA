import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, simpledialog, ttk
from typing import Dict, List, Optional
from uuid import uuid4

from core.backup import create_backup
from core.config_manager import ConfigManager, ensure_paths
from core.csv_storage import read_items, read_money, write_items, write_money
from core.models import ItemRecord, MoneyRecord
from scoring.scoring import ScoreResult, score_item


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

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True)

        self.purchases_view = PurchasesView(self, self)
        self.money_view = MoneyView(self, self)
        self.settings_view = SettingsView(self, self)

        self.notebook.add(self.purchases_view, text="Purchases")
        self.notebook.add(self.money_view, text="Money")
        self.notebook.add(self.settings_view, text="Settings")

        self._load_data()

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
        self.style.configure("Treeview", background=row_bg, foreground=fg, fieldbackground=row_bg)
        self.style.map("TButton", background=[("active", accent)])
        self.style.configure("HighScore.Treeview", foreground="#16a34a")
        self.style.configure("LowScore.Treeview", foreground="#dc2626")

    def _load_data(self) -> None:
        self.items = read_items(self.items_path)
        self.money = read_money(self.money_path)
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
            self.save_money(trigger_backup=self.settings["ui"].get("autosave", True))

    def change_theme(self, name: str) -> None:
        self.theme = self.config_manager.get_theme(name)
        self.config_manager.set_default_theme(name)
        self._apply_theme()
        self.purchases_view.refresh_table()
        self.money_view.refresh_table()
        self.settings_view.refresh_theme_dropdown()


class PurchasesView(ttk.Frame):
    def __init__(self, parent, app: FinancePlannerApp):
        super().__init__(parent)
        self.app = app
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

        columns = ("product", "date", "cost", "urgency", "overall")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        headings = ["Product", "Date", "Cost", "Urgency", "Overall"]
        for col, text in zip(columns, headings):
            self.tree.heading(col, text=text, command=lambda c=col: self._sort_by(c, False))
            self.tree.column(col, width=120, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)

    def refresh_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        for item in self.app.items:
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
        self.tree.tag_configure("high", foreground="#16a34a")
        self.tree.tag_configure("low", foreground="#dc2626")

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

    def _edit_item(self) -> None:
        record = self._get_selected_item()
        if not record:
            messagebox.showinfo("Edit Item", "Select a row to edit.")
            return
        self.app.add_or_edit_item(record)

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
        self.app.items = imported
        self.app.save_items(trigger_backup=self.app.settings["ui"].get("autosave", True))


class MoneyView(ttk.Frame):
    def __init__(self, parent, app: FinancePlannerApp):
        super().__init__(parent)
        self.app = app
        self._build_ui()

    def _build_ui(self) -> None:
        btn_frame = ttk.Frame(self)
        btn_frame.pack(fill="x", padx=8, pady=6)
        ttk.Button(btn_frame, text="Add Entry", command=self._add_entry).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Edit Selected", command=self._edit_entry).pack(side="left", padx=4)
        ttk.Button(btn_frame, text="Refresh", command=self.refresh_table).pack(side="left", padx=4)

        columns = ("date", "type", "source", "amount", "linked_item")
        self.tree = ttk.Treeview(self, columns=columns, show="headings")
        headings = ["Date", "Type", "Source/Destination", "Amount", "Linked Item"]
        for col, text in zip(columns, headings):
            self.tree.heading(col, text=text)
            self.tree.column(col, width=140, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=8, pady=6)

    def refresh_table(self) -> None:
        for row in self.tree.get_children():
            self.tree.delete(row)
        id_to_product = {item.id: item.product for item in self.app.items}
        for entry in self.app.money:
            linked_display = id_to_product.get(entry.linked_item_id, entry.linked_item_id)
            self.tree.insert(
                "",
                "end",
                iid=entry.id,
                values=(
                    entry.date.strftime(self.app.date_fmt),
                    entry.entry_type,
                    entry.source_or_destination,
                    f"{self.app.currency_symbol}{entry.amount:.2f}",
                    linked_display,
                ),
            )

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

    def _edit_entry(self) -> None:
        record = self._get_selected_entry()
        if not record:
            messagebox.showinfo("Edit Entry", "Select a row to edit.")
            return
        self.app.add_money_entry(record)


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


class ItemDialog:
    def __init__(self, app: FinancePlannerApp, existing: Optional[ItemRecord] = None):
        self.app = app
        self.top = tk.Toplevel(app)
        self.top.title("Item" if not existing else "Edit Item")
        self.top.grab_set()
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
        ttk.Entry(self.top, textvariable=self.date_var).grid(row=0, column=1, sticky="ew", **pad)

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
        self.result: Optional[MoneyRecord] = None
        self.existing = existing
        self._build_ui()
        if existing:
            self._load(existing)

    def _build_ui(self) -> None:
        pad = {"padx": 6, "pady": 4}
        self.date_var = tk.StringVar(value=datetime.now().strftime(self.app.date_fmt))
        ttk.Label(self.top, text="Date").grid(row=0, column=0, sticky="w", **pad)
        ttk.Entry(self.top, textvariable=self.date_var).grid(row=0, column=1, sticky="ew", **pad)

        ttk.Label(self.top, text="Type (income/expense)").grid(row=1, column=0, sticky="w", **pad)
        self.type_var = tk.StringVar(value="income")
        ttk.Entry(self.top, textvariable=self.type_var).grid(row=1, column=1, sticky="ew", **pad)

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


def launch() -> None:
    config = ConfigManager()
    app = FinancePlannerApp(config)
    app.mainloop()


if __name__ == "__main__":
    launch()
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
