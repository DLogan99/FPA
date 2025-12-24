import json
import os
import shutil
import sys
from typing import Any, Dict, Optional


class ConfigManager:
    """Loads and provides access to settings, weights, and themes."""

    def __init__(
        self,
        settings_path: str = "config/settings.json",
        weights_path: str = "config/weights.json",
        themes_path: str = "config/themes.json",
        base_dir: Optional[str] = None,
    ) -> None:
        self.bundle_dir = getattr(sys, "_MEIPASS", os.getcwd())
        self.base_dir = os.path.abspath(base_dir or self.bundle_dir)
        self.user_root = self._user_data_root()
        self.settings_path = self._user_path(settings_path)
        self.weights_path = self._user_path(weights_path)
        self.themes_path = self._user_path(themes_path)
        self.settings = self._load_json(
            self.settings_path,
            default=self._default_settings(),
            packaged_name=settings_path,
        )
        self.weights = self._load_json(
            self.weights_path,
            default=self._default_weights(),
            packaged_name=weights_path,
        )
        self.themes = self._load_json(
            self.themes_path,
            default=self._default_themes(),
            packaged_name=themes_path,
        )
        self._apply_defaults()

    @staticmethod
    def _user_data_root() -> str:
        if os.name == "nt":
            base = os.environ.get("APPDATA") or os.path.expanduser("~\\AppData\\Roaming")
        else:
            base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
        return os.path.join(base, "finance_planner")

    def _user_path(self, relative: str) -> str:
        if os.path.isabs(relative):
            return relative
        return os.path.join(self.user_root, relative)

    def _load_json(self, path: str, default: Dict[str, Any], packaged_name: Optional[str] = None) -> Dict[str, Any]:
        if not os.path.exists(path):
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if packaged_name:
                packaged_path = os.path.join(self.bundle_dir, packaged_name)
                if os.path.exists(packaged_path):
                    shutil.copy2(packaged_path, path)
            if not os.path.exists(path):
                with open(path, "w", encoding="utf-8") as f:
                    json.dump(default, f, indent=2)
                return dict(default)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    @staticmethod
    def _default_settings() -> Dict[str, Any]:
        return {
            "paths": {
                "items_csv": "",
                "money_csv": "",
                "backup_dir": "",
            },
            "backup": {
                "keep_recent": 3,
                "keep_historical": 3,
            },
            "themes": {"default": "light"},
            "ui": {
                "date_format": "%Y-%m-%d %H:%M",
                "currency_symbol": "$",
                "autosave": True,
            },
        }

    @staticmethod
    def _default_weights() -> Dict[str, Any]:
        return {
            "weights": {
                "date": 1.0,
                "cost": 1.0,
                "urgency": 1.0,
                "value": 1.0,
                "price_comp": 1.0,
                "effect": 1.0,
            },
            "date_scoring": {"recent_days": 7, "mid_days": 30},
            "cost_bands": [
                {"max": 50, "score": 5},
                {"max": 150, "score": 4},
                {"max": 400, "score": 3},
                {"max": 800, "score": 2},
                {"max": None, "score": 1},
            ],
            "urgency_override": 5,
        }

    @staticmethod
    def _default_themes() -> Dict[str, Any]:
        # Minimal fallback; the bundled themes.json has richer content.
        return {
            "light": {
                "background": "#f7f9fb",
                "foreground": "#0f172a",
                "accent": "#2563eb",
                "muted": "#94a3b8",
                "table": {
                    "header_bg": "#e2e8f0",
                    "header_fg": "#0f172a",
                    "row_bg": "#ffffff",
                    "alt_row_bg": "#f1f5f9",
                },
            }
        }

    def _rel(self, path: str) -> str:
        if os.path.isabs(path):
            return path
        return os.path.join(self.base_dir, path)

    def _apply_defaults(self) -> None:
        paths = self.settings.setdefault("paths", {})
        paths.setdefault("items_csv", os.path.join(self.user_root, "data", "items.csv"))
        paths.setdefault("money_csv", os.path.join(self.user_root, "data", "money.csv"))
        paths.setdefault("backup_dir", os.path.join(self.user_root, "backups"))
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
    for key in ("items_csv", "money_csv", "backup_dir"):
        path = paths.get(key)
        if path:
            os.makedirs(os.path.dirname(path) if key != "backup_dir" else path, exist_ok=True)
