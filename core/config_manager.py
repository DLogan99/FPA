import json
import os
import sys
from typing import Any, Dict, Optional


class ConfigManager:
    """Loads and provides access to settings, weights, and themes."""

    def __init__(
        self,
        settings_path: str = "config/settings.json",
        weights_path: str = "config/weights.json",
        themes_path: str = "config/themes.json",
    ) -> None:
        self.base_dir = getattr(sys, "_MEIPASS", os.getcwd())
        self.settings_path = self._rel(settings_path)
        self.weights_path = self._rel(weights_path)
        self.themes_path = self._rel(themes_path)
        self.settings = self._load_json(self.settings_path, default={})
        self.weights = self._load_json(self.weights_path, default={})
        self.themes = self._load_json(self.themes_path, default={})
        self._apply_defaults()

    @staticmethod
    def _load_json(path: str, default: Dict[str, Any]) -> Dict[str, Any]:
        if not os.path.exists(path):
            return dict(default)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _rel(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)

    def _apply_defaults(self) -> None:
        self.settings.setdefault(
            "paths",
            {
                "items_csv": os.path.join(self.base_dir, "data", "items.csv"),
                "money_csv": os.path.join(self.base_dir, "data", "money.csv"),
                "backup_dir": os.path.join(self.base_dir, "backups"),
            },
        )
        self.settings.setdefault(
            "backup",
            {
                "keep_recent": 3,
                "keep_historical": 3,
            },
        )
        self.settings.setdefault("themes", {"default": "light"})
        self.settings.setdefault(
            "ui",
            {
                "date_format": "%Y-%m-%d %H:%M",
                "currency_symbol": "$",
                "autosave": True,
            },
        )
        self.weights.setdefault(
            "weights",
            {
                "date": 1.0,
                "cost": 1.0,
                "urgency": 1.0,
                "value": 1.0,
                "price_comp": 1.0,
                "effect": 1.0,
            },
        )
        self.weights.setdefault("date_scoring", {"recent_days": 7, "mid_days": 30})
        self.weights.setdefault(
            "cost_bands",
            [
                {"max": 50, "score": 5},
                {"max": 150, "score": 4},
                {"max": 400, "score": 3},
                {"max": 800, "score": 2},
                {"max": None, "score": 1},
            ],
        )
        self.weights.setdefault("urgency_override", 5)
        # ensure every theme has table defaults to avoid KeyError when packed
        for name, theme in list(self.themes.items()):
            theme.setdefault("table", {})
            table = theme["table"]
            table.setdefault("header_bg", theme.get("background", "#ffffff"))
            table.setdefault("header_fg", theme.get("foreground", "#000000"))
            table.setdefault("row_bg", theme.get("background", "#ffffff"))
            table.setdefault("alt_row_bg", theme.get("background", "#ffffff"))

    def save_settings(self) -> None:
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2)

    def save_themes(self) -> None:
        os.makedirs(os.path.dirname(self.themes_path), exist_ok=True)
        with open(self.themes_path, "w", encoding="utf-8") as f:
            json.dump(self.themes, f, indent=2)

    def save_weights(self) -> None:
        os.makedirs(os.path.dirname(self.weights_path), exist_ok=True)
        with open(self.weights_path, "w", encoding="utf-8") as f:
            json.dump(self.weights, f, indent=2)

    def get_theme(self, name: Optional[str] = None) -> Dict[str, Any]:
        theme_name = name or self.settings.get("themes", {}).get("default", "light")
        base = self.themes.get("light", {})
        selected = self.themes.get(theme_name, base)
        # ensure required keys exist
        theme = {
            "background": selected.get("background", base.get("background", "#ffffff")),
            "foreground": selected.get("foreground", base.get("foreground", "#000000")),
            "accent": selected.get("accent", base.get("accent", "#2563eb")),
            "muted": selected.get("muted", base.get("muted", "#94a3b8")),
        }
        table = selected.get("table", {}) or {}
        base_table = base.get("table", {}) or {}
        theme["table"] = {
            "header_bg": table.get("header_bg", base_table.get("header_bg", theme["background"])),
            "header_fg": table.get("header_fg", base_table.get("header_fg", theme["foreground"])),
            "row_bg": table.get("row_bg", base_table.get("row_bg", theme["background"])),
            "alt_row_bg": table.get("alt_row_bg", base_table.get("alt_row_bg", theme["background"])),
        }
        return theme

    def set_default_theme(self, name: str) -> None:
        self.settings.setdefault("themes", {})
        self.settings["themes"]["default"] = name
        self.save_settings()


def ensure_paths(settings: Dict[str, Any]) -> None:
    """Ensure directories for data and backups exist."""
    paths = settings.get("paths", {})
    for key in ("items_csv", "money_csv"):
        path = paths.get(key)
        if path:
            os.makedirs(os.path.dirname(path), exist_ok=True)
    backup_dir = paths.get("backup_dir")
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)
