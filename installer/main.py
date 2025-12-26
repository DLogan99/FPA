import argparse
import csv
import importlib
import importlib.util
import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

from core.config_manager import ConfigManager
from core.models import ItemRecord, MoneyRecord


DEFAULT_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "FinancePlanner")
START_MENU_DIR = Path(os.environ.get("APPDATA") or Path.home() / ".local/share") / "Microsoft" / "Windows" / "Start Menu" / "Programs"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE") or Path.home()) / "Desktop"
USER_DATA_ROOT = Path(ConfigManager._user_data_root())
APPDATA_DIR = USER_DATA_ROOT
DEFAULT_EXE_PATH = Path("dist") / "finance_planner.exe"
DEFAULT_ARCHIVE_PATH = Path("dist") / "finance_planner.zip"


def _load_pywin32():
    pythoncom_spec = importlib.util.find_spec("pythoncom")
    win32com_spec = importlib.util.find_spec("win32com.client")
    if pythoncom_spec and win32com_spec:
        pythoncom_module = importlib.import_module("pythoncom")
        win32com_module = importlib.import_module("win32com.client")
        return pythoncom_module, win32com_module
    return None, None


def ensure_user_data_root() -> None:
    required_dirs = [
        APPDATA_DIR,
        APPDATA_DIR / "data",
        APPDATA_DIR / "backups",
    ]
    for path in required_dirs:
        path.mkdir(parents=True, exist_ok=True)


def prime_user_data(config_src: Path) -> None:
    """Create default user config and data files in APPDATA."""
    ensure_user_data_root()

    settings_dst = APPDATA_DIR / "settings.json"
    themes_dst = APPDATA_DIR / "themes.json"
    weights_dst = APPDATA_DIR / "weights.txt"
    items_dst = APPDATA_DIR / "data" / "items.csv"
    money_dst = APPDATA_DIR / "data" / "money.csv"

    _copy_or_create_json(config_src / "settings.json", settings_dst, ConfigManager._default_settings())
    _copy_or_create_json(config_src / "themes.json", themes_dst, ConfigManager._default_themes())
    _copy_or_create_text(config_src / "weights.txt", weights_dst, _weights_template(ConfigManager._default_weights()))
    _ensure_csv(items_dst, ItemRecord.headers())
    _ensure_csv(money_dst, MoneyRecord.headers())


def _copy_or_create_json(src: Path, dst: Path, default: dict) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.exists():
        shutil.copy2(src, dst)
        return
    with open(dst, "w", encoding="utf-8") as fh:
        json.dump(default, fh, indent=2)


def _copy_or_create_text(src: Path, dst: Path, contents: str) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        return
    if src.exists():
        shutil.copy2(src, dst)
        return
    dst.write_text(contents, encoding="utf-8")


def _ensure_csv(path: Path, headers: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()


def _weights_template(config: dict) -> str:
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


def copy_tree(src: Path, dst: Path) -> None:
    if not src.exists():
        raise FileNotFoundError(f"Source path does not exist: {src}")
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return
    for root, _, files in os.walk(src):
        rel_root = Path(root).relative_to(src)
        for file in files:
            source_file = Path(root) / file
            dest_file = dst / rel_root / file
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, dest_file)


def build_archive(exe_path: Path, config_src: Path, archive_path: Path) -> Path:
    if not exe_path.exists():
        raise FileNotFoundError(f"Executable not found at {exe_path}. Build with PyInstaller first.")
    if not config_src.exists():
        raise FileNotFoundError(f"Config folder not found: {config_src}")
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.write(exe_path, arcname=exe_path.name)
        for root, _, files in os.walk(config_src):
            root_path = Path(root)
            rel_root = root_path.relative_to(config_src.parent)
            for file in files:
                file_path = root_path / file
                zf.write(file_path, arcname=rel_root / file)
    return archive_path


def extract_payload(archive_path: Path, install_dir: Path) -> None:
    with zipfile.ZipFile(archive_path, "r") as zf:
        zf.extractall(install_dir)


def create_shortcut(target: Path, shortcut_path: Path, working_dir: Optional[Path] = None, icon: Optional[Path] = None) -> None:
    pythoncom, win32com = _load_pywin32()
    if win32com is None or pythoncom is None:
        raise RuntimeError("Shortcut creation requires pywin32 on Windows.")
    pythoncom.CoInitialize()
    shell = win32com.client.Dispatch("WScript.Shell")
    shortcut = shell.CreateShortCut(str(shortcut_path))
    shortcut.Targetpath = str(target)
    shortcut.WorkingDirectory = str(working_dir or target.parent)
    if icon:
        shortcut.IconLocation = str(icon)
    shortcut.save()


def pin_to_taskbar(target: Path) -> None:
    # Uses taskbar pinning verb exposed via ShellExecute
    pythoncom, win32com = _load_pywin32()
    if win32com is None or pythoncom is None:
        raise RuntimeError("Taskbar pinning requires pywin32 on Windows.")
    pythoncom.CoInitialize()
    shell = win32com.client.Dispatch("Shell.Application")
    folder = shell.Namespace(target.parent)
    item = folder.ParseName(target.name)
    if item is None:
        raise RuntimeError(f"Unable to locate file for pinning: {target}")
    verbs = item.Verbs()
    for i in range(verbs.Count):
        verb = verbs.Item(i)
        name = verb.Name.replace("&", "").strip().lower()
        if "taskbar" in name or "pin to taskbar" in name:
            verb.DoIt()
            return
    raise RuntimeError("Taskbar pin verb not available (may require elevation or Windows 10+).")


def create_shortcuts(target: Path, start_menu: bool, desktop: bool, taskbar: bool) -> List[Tuple[str, Path]]:
    created: List[Tuple[str, Path]] = []
    if start_menu:
        shortcut = START_MENU_DIR / "Finance Planner.lnk"
        create_shortcut(target, shortcut)
        created.append(("start_menu", shortcut))
    if desktop:
        shortcut = DESKTOP_DIR / "Finance Planner.lnk"
        create_shortcut(target, shortcut)
        created.append(("desktop", shortcut))
    if taskbar:
        pin_to_taskbar(target)
        created.append(("taskbar", target))
    return created


def remove_shortcuts(shortcuts: Iterable[Path]) -> None:
    for path in shortcuts:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def install(
    install_dir: Path,
    include_start_menu: bool = True,
    include_desktop: bool = False,
    include_taskbar: bool = False,
    exe_path: Path = DEFAULT_EXE_PATH,
    archive_path: Path = DEFAULT_ARCHIVE_PATH,
    config_src: Path = Path("config"),
) -> None:
    install_dir.mkdir(parents=True, exist_ok=True)
    used_archive = False

    if archive_path.exists():
        extract_payload(archive_path, install_dir)
        used_archive = True
    else:
        if not exe_path.exists():
            raise FileNotFoundError(
                f"Neither archive ({archive_path}) nor executable ({exe_path}) found. Build artifacts first."
            )
        if not config_src.exists():
            raise FileNotFoundError(f"Config folder not found at {config_src}. Ensure bundled defaults are available.")
        copy_tree(exe_path, install_dir / exe_path.name)
        copy_tree(config_src, install_dir / "config")

    config_target = install_dir / "config"
    if not config_target.exists():
        raise FileNotFoundError(f"Config folder missing after install: {config_target}")

    prime_user_data(config_target)

    ensure_user_data_root()

    target_exe = install_dir / exe_path.name
    if not target_exe.exists():
        raise FileNotFoundError(f"Installed executable not found at {target_exe}")

    created_shortcuts = create_shortcuts(
        target_exe,
        start_menu=include_start_menu,
        desktop=include_desktop,
        taskbar=include_taskbar,
    )
    if used_archive:
        print(f"Installed from archive: {archive_path}")
    else:
        print(f"Installed from executable: {exe_path}")
    print("Installation completed.")
    for name, path in created_shortcuts:
        print(f"Created {name} shortcut: {path}")


def uninstall(install_dir: Path) -> None:
    shortcuts = [
        START_MENU_DIR / "Finance Planner.lnk",
        DESKTOP_DIR / "Finance Planner.lnk",
    ]
    remove_shortcuts(shortcuts)
    if install_dir.exists():
        shutil.rmtree(install_dir, ignore_errors=True)
    print("Uninstall completed. User data under %APPDATA%/finance_planner remains untouched.")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Finance Planner installer")
    parser.add_argument(
        "--install-dir",
        type=Path,
        default=DEFAULT_INSTALL_DIR,
        help="Target install directory (default: %(default)s)",
    )
    parser.add_argument("--no-start-menu", action="store_true", help="Skip creating a Start Menu shortcut")
    parser.add_argument("--desktop", action="store_true", help="Create a Desktop shortcut")
    parser.add_argument("--taskbar", action="store_true", help="Pin to the taskbar (may require elevation)")
    parser.add_argument("--uninstall", action="store_true", help="Remove installed files and shortcuts")
    parser.add_argument(
        "--archive",
        type=Path,
        default=DEFAULT_ARCHIVE_PATH,
        help="Path to a compressed installer payload (default: %(default)s)",
    )
    parser.add_argument(
        "--app-exe",
        type=Path,
        default=DEFAULT_EXE_PATH,
        help="Path to the built application executable (default: %(default)s)",
    )
    parser.add_argument(
        "--config-src",
        type=Path,
        default=Path("config"),
        help="Path to the config folder to bundle or install (default: %(default)s)",
    )
    parser.add_argument(
        "--build-archive",
        action="store_true",
        help="Build the compressed installer payload and exit (no installation performed)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    if args.build_archive:
        archive = build_archive(args.app_exe, args.config_src, args.archive)
        print(f"Archive created at {archive}")
        return

    if args.uninstall:
        uninstall(args.install_dir)
        return

    install(
        install_dir=args.install_dir,
        include_start_menu=not args.no_start_menu,
        include_desktop=args.desktop,
        include_taskbar=args.taskbar,
        exe_path=args.app_exe,
        archive_path=args.archive,
        config_src=args.config_src,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
