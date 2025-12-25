import argparse
import importlib
import importlib.util
import os
import shutil
import sys
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


DEFAULT_INSTALL_DIR = Path(os.environ.get("LOCALAPPDATA", "")) / "FinancePlanner"
START_MENU_DIR = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
DESKTOP_DIR = Path(os.environ.get("USERPROFILE", "")) / "Desktop"
APPDATA_DIR = Path(os.environ.get("APPDATA", "")) / "finance_planner"


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
        APPDATA_DIR / "data",
        APPDATA_DIR / "backups",
    ]
    for path in required_dirs:
        path.mkdir(parents=True, exist_ok=True)


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
) -> None:
    exe_path = Path("dist") / "finance_planner.exe"
    config_src = Path("config")

    if not exe_path.exists():
        raise FileNotFoundError(f"Executable not found at {exe_path}. Build with PyInstaller first.")
    if not config_src.exists():
        raise FileNotFoundError("Config folder not found. Ensure bundled defaults are available.")

    install_dir.mkdir(parents=True, exist_ok=True)
    copy_tree(exe_path, install_dir / exe_path.name)
    copy_tree(config_src, install_dir / "config")

    ensure_user_data_root()

    created_shortcuts = create_shortcuts(
        install_dir / exe_path.name,
        start_menu=include_start_menu,
        desktop=include_desktop,
        taskbar=include_taskbar,
    )
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
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    if args.uninstall:
        uninstall(args.install_dir)
        return

    install(
        install_dir=args.install_dir,
        include_start_menu=not args.no_start_menu,
        include_desktop=args.desktop,
        include_taskbar=args.taskbar,
    )


if __name__ == "__main__":
    main(sys.argv[1:])
