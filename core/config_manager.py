import csv
import json
import os
import re
import shutil
import sys
from copy import deepcopy
from typing import Any, Dict, List, Optional, Tuple

from core.models import ItemRecord, MoneyRecord


class ConfigManager:
    """Loads and provides access to settings, weights, and themes."""

    def __init__(
        self,
        settings_path: str = "config/settings.json",
        weights_path: str = "config/weights.txt",
        themes_path: str = "config/themes.json",
        base_dir: Optional[str] = None,
    ) -> None:
        self.bundle_dir = getattr(sys, "_MEIPASS", os.getcwd())
        self.base_dir = os.path.abspath(base_dir or self.bundle_dir)
        self.user_root = self._user_data_root()
        self.load_messages: List[str] = []
        self.settings_path = self._user_path(settings_path)
        self.weights_path = self._user_path(weights_path)
        self.themes_path = self._user_path(themes_path)
        self.settings = self._load_json(
            self.settings_path,
            default=self._default_settings(),
            packaged_name=settings_path,
        )
        self.weights, weights_messages = self._load_weights_text(
            self.weights_path,
            default=self._default_weights(),
            packaged_name=weights_path,
        )
        self.load_messages.extend(weights_messages)
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

    def _load_weights_text(
        self, path: str, default: Dict[str, Any], packaged_name: Optional[str] = None
    ) -> Tuple[Dict[str, Any], List[str]]:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        warnings: List[str] = []
        created = False
        if not os.path.exists(path):
            if packaged_name:
                packaged_path = os.path.join(self.bundle_dir, packaged_name)
                if os.path.exists(packaged_path):
                    shutil.copy2(packaged_path, path)
            if not os.path.exists(path):
                created = True
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._weights_template(default))
        try:
            with open(path, "r", encoding="utf-8") as f:
                contents = f.readlines()
            weights, parse_warnings = self._parse_weights_lines(contents, default)
            warnings.extend(parse_warnings)
            if created:
                warnings.append(f"Weights file not found. A default template was created at {path}.")
            return weights, warnings
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"Failed to load weights from {path}: {exc}. Using defaults.")
            return dict(default), warnings

    def _parse_weights_lines(self, lines: List[str], default: Dict[str, Any]) -> Tuple[Dict[str, Any], List[str]]:
        config = deepcopy(default)
        warnings: List[str] = []
        weight_keys = {
            "weight_date": "date",
            "weight_cost": "cost",
            "weight_urgency": "urgency",
            "weight_value": "value",
            "weight_want": "want",
            "weight_price_comp": "price_comp",
            "weight_effect": "effect",
        }
        for idx, raw in enumerate(lines, start=1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                warnings.append(f"Line {idx}: missing '=' separator; ignored.")
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if key in weight_keys:
                try:
                    config["weights"][weight_keys[key]] = float(value)
                except ValueError:
                    warnings.append(f"Line {idx}: invalid weight for {key}; using default.")
                continue
            if key == "date_recent_days":
                try:
                    config.setdefault("date_scoring", {})["recent_days"] = int(value)
                except ValueError:
                    warnings.append(f"Line {idx}: invalid integer for date_recent_days; using default.")
                continue
            if key == "date_mid_days":
                try:
                    config.setdefault("date_scoring", {})["mid_days"] = int(value)
                except ValueError:
                    warnings.append(f"Line {idx}: invalid integer for date_mid_days; using default.")
                continue
            cost_band_match = re.match(r"cost_band(\d+)_(max|score)$", key)
            if cost_band_match:
                band_num = int(cost_band_match.group(1))
                band_field = cost_band_match.group(2)
                while len(config.setdefault("cost_bands", [])) < band_num:
                    config["cost_bands"].append({"max": None, "score": 1})
                band = config["cost_bands"][band_num - 1]
                if band_field == "max":
                    if value.lower() in {"none", ""}:
                        band["max"] = None
                    else:
                        try:
                            band["max"] = float(value)
                        except ValueError:
                            warnings.append(f"Line {idx}: invalid max for {key}; using default.")
                else:
                    try:
                        band["score"] = float(value)
                    except ValueError:
                        warnings.append(f"Line {idx}: invalid score for {key}; using default.")
            if key.startswith("cost_band"):
                suffix = key[len("cost_band") :]
                if "_" in suffix:
                    band_idx_str, field = suffix.split("_", 1)
                    if band_idx_str.isdigit() and field in {"max", "score"}:
                        band_num = int(band_idx_str)
                        while len(config.setdefault("cost_bands", [])) < band_num:
                            config["cost_bands"].append({"max": None, "score": 1})
                        band = config["cost_bands"][band_num - 1]
                        if field == "max":
                            if value.lower() in {"none", ""}:
                                band["max"] = None
                            else:
                                try:
                                    band["max"] = float(value)
                                except ValueError:
                                    warnings.append(f"Line {idx}: invalid max for {key}; using default.")
                        else:
                            try:
                                band["score"] = float(value)
                            except ValueError:
                                warnings.append(f"Line {idx}: invalid score for {key}; using default.")
                        continue
                warnings.append(f"Line {idx}: invalid band index in {key}; ignored.")
                continue
            if key == "urgency_override":
                try:
                    config["urgency_override"] = int(value)
                except ValueError:
                    warnings.append(f"Line {idx}: invalid integer for urgency_override; using default.")
                continue
            warnings.append(f"Line {idx}: unknown key '{key}'; ignored.")
        return config, warnings

    def _weights_template(self, config: Dict[str, Any]) -> str:
        weights = config.get("weights", {})
        date_scoring = config.get("date_scoring", {})
        bands = config.get("cost_bands", [])
        lines = [
            "# Purchase scoring weights",
            "# Edit values and restart the app to apply changes.",
            "",
            f"weight_date={weights.get('date', 1.0)}",
            f"weight_cost={weights.get('cost', 1.0)}",
            f"weight_urgency={weights.get('urgency', 1.0)}",
            f"weight_value={weights.get('value', 1.0)}",
            f"weight_want={weights.get('want', 1.0)}",
            f"weight_price_comp={weights.get('price_comp', 1.0)}",
            f"weight_effect={weights.get('effect', 1.0)}",
            "",
            f"date_recent_days={date_scoring.get('recent_days', 7)}",
            f"date_mid_days={date_scoring.get('mid_days', 30)}",
            "",
            "# Cost bands: ascending maximum (use 'none' for no upper bound)",
        ]
        for idx, band in enumerate(bands, start=1):
            max_val = band.get("max")
            max_str = "none" if max_val is None else max_val
            lines.append(f"cost_band{idx}_max={max_str}")
            lines.append(f"cost_band{idx}_score={band.get('score', 1)}")
        lines.append("")
        lines.append(f"urgency_override={config.get('urgency_override', 5)}")
        return "\n".join(str(line) for line in lines)

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
                "want": 1.0,
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
        changed = False

        if not paths.get("items_csv"):
            paths["items_csv"] = os.path.join(self.user_root, "data", "items.csv")
            changed = True
        if not paths.get("money_csv"):
            paths["money_csv"] = os.path.join(self.user_root, "data", "money.csv")
            changed = True
        if not paths.get("backup_dir"):
            paths["backup_dir"] = os.path.join(self.user_root, "backups")
            changed = True

        backup_defaults = {
            "keep_recent": 3,
            "keep_historical": 3,
        }
        if "backup" not in self.settings:
            self.settings["backup"] = dict(backup_defaults)
            changed = True
        else:
            for key, value in backup_defaults.items():
                if key not in self.settings["backup"]:
                    self.settings["backup"][key] = value
                    changed = True

        if "themes" not in self.settings:
            self.settings["themes"] = {"default": "light"}
            changed = True
        else:
            if "default" not in self.settings["themes"]:
                self.settings["themes"]["default"] = "light"
                changed = True

        ui_defaults = {
            "date_format": "%Y-%m-%d %H:%M",
            "currency_symbol": "$",
            "autosave": True,
        }
        if "ui" not in self.settings:
            self.settings["ui"] = dict(ui_defaults)
            changed = True
        else:
            for key, value in ui_defaults.items():
                if key not in self.settings["ui"]:
                    self.settings["ui"][key] = value
                    changed = True

        self.weights.setdefault(
            "weights",
            {
                "date": 1.0,
                "cost": 1.0,
                "urgency": 1.0,
                "value": 1.0,
                "want": 1.0,
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

        if changed:
            self.save_settings()

    def save_settings(self) -> None:
        os.makedirs(os.path.dirname(self.settings_path), exist_ok=True)
        with open(self.settings_path, "w", encoding="utf-8") as f:
            json.dump(self.settings, f, indent=2)

    def save_themes(self) -> None:
        os.makedirs(os.path.dirname(self.themes_path), exist_ok=True)
        with open(self.themes_path, "w", encoding="utf-8") as f:
            json.dump(self.themes, f, indent=2)

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


def ensure_startup_files(config: "ConfigManager") -> None:
    """Create all files the application expects at startup if they are missing."""
    _ensure_json_if_missing(config.settings_path, config.settings)
    _ensure_text_if_missing(config.weights_path, config._weights_template(config.weights))
    _ensure_json_if_missing(config.themes_path, config.themes)

    paths = config.settings.get("paths", {})
    _ensure_csv_if_missing(paths.get("items_csv"), ItemRecord.headers())
    _ensure_csv_if_missing(paths.get("money_csv"), MoneyRecord.headers())
    backup_dir = paths.get("backup_dir")
    if backup_dir:
        os.makedirs(backup_dir, exist_ok=True)


def _ensure_json_if_missing(path: Optional[str], payload: Dict[str, Any]) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)


def _ensure_text_if_missing(path: Optional[str], contents: str) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(contents)


def _ensure_csv_if_missing(path: Optional[str], headers: List[str]) -> None:
    if not path:
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.exists(path):
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=headers)
            writer.writeheader()
