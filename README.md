# Finance Planner (Python)

Local-first finance planner built with PySide6 (Qt). Data is stored in CSV files with configurable JSON settings and themes plus a plain-text weights file. Defaults are bundled and copied to your OS data directory on first run (e.g., `%APPDATA%/finance_planner` on Windows or `~/.local/share/finance_planner` on Linux).

## Features
- Purchases/Items: add, edit, view, delete, import/export CSV, search/filter, and score via configurable weights with total spend, average score, and item counts.
- Money: track income/expense entries, search/filter, import/export CSV, link to purchases by ID, and see income/expense totals with a running balance.
- Keyboard and mouse shortcuts: double-click rows to edit, Ctrl+F to search, Ctrl+N/Ctrl+E to add/edit.
- Quick filtering: score filters for purchases (high/low) and type filters for money (income/expense) alongside text search.
- Date pickers: calendar popup in item and money dialogs for quick date selection.
- Settings: toggle autosave, select theme, back up on-demand, open the data or config folders, and copy key file paths (items, money, backups, settings/weights/themes).
- Backups: timestamped copies with retention (3 recent + 3 historical by default).
- Config and themes are user-writable JSON in the data directory; defaults are auto-created on first run. Edit `settings.json` to change currency/date formats or backup retention.
- Weights: edit `weights.txt` (key=value lines) and restart the app to apply changes.

## Install / Run
Install dependencies (PySide6 for the Qt UI) then run:

```bash
pip install PySide6
python app.py
```

On Windows, prefer `pythonw.exe app.py` to avoid launching a console window when running the app directly.

## Data locations
- Config: `<data_dir>/settings.json`
- Weights: `<data_dir>/weights.txt`
- Themes: `<data_dir>/themes.json`
- Items: `<data_dir>/data/items.csv`
- Money: `<data_dir>/data/money.csv`
- Backups: `<data_dir>/backups/`

## Building standalone binaries (PyInstaller)
```bash
# Linux/macOS
pyinstaller app.py --onefile --windowed --noconsole --name finance_planner --add-data "config:config"

# Windows (note the path separator)
pyinstaller app.py --onefile --windowed --noconsole --name finance_planner --add-data "config;config"
```

Binaries will appear under `dist/` (`finance_planner` on Linux/macOS, `finance_planner.exe` on Windows).

## Windows installer helper

Build the binary with PyInstaller as above (including `--noconsole`) to ensure the packaged app runs without a console window, then run the installer helper:

```bash
python -m installer.main
```

Options:
- `--install-dir PATH` (default: `%LOCALAPPDATA%\FinancePlanner`)
- `--no-start-menu` to skip the Start Menu shortcut
- `--desktop` to add a Desktop shortcut
- `--taskbar` to attempt pinning to the taskbar (may require elevation)
- `--uninstall` to remove installed files and shortcuts (user data under `%APPDATA%\finance_planner` is preserved)
