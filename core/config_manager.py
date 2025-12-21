import json
import os
from typing import Any, Dict, Optional


class ConfigManager:
    """Loads and provides access to settings, weights, and themes."""

    def __init__(
        self,
        settings_path: str = "config/settings.json",
        weights_path: str = "config/weights.json",
        themes_path: str = "config/themes.json",
    ) -> None:
        self.settings_path = settings_path
        self.weights_path = weights_path
        self.themes_path = themes_path
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

    def _apply_defaults(self) -> None:
        self.settings.setdefault(
            "paths",
            {
                "items_csv": "data/items.csv",
                "money_csv": "data/money.csv",
                "backup_dir": "backups",
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
        return self.themes.get(theme_name, self.themes.get("light", {}))

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
