# Finance Planner (Python)

Local-first finance planner built with Tkinter. Data is stored in CSV files with configurable JSON settings, weights, and themes. Defaults are bundled and copied to your OS data directory on first run (e.g., `%APPDATA%/finance_planner` on Windows or `~/.local/share/finance_planner` on Linux).

## Features
- Purchases/Items: add, edit, view, delete, import/export CSV, search/filter, and score via configurable weights with total spend, average score, and item counts.
- Money: track income/expense entries, search/filter, import/export CSV, link to purchases by ID, and see income/expense totals with a running balance and entry counts.
- Keyboard and mouse shortcuts: double-click rows to edit, Delete to remove selected rows, Ctrl+F to search, Ctrl+N/Ctrl+E to add/edit, Enter to edit a selected row.
- Shortcut help: press F1 or use Help → Keyboard shortcuts for a quick list.
- Quick filtering: score filters for purchases (high/low) and type filters for money (income/expense) alongside text search.
- Settings: update UI basics, back up on-demand, and open the data folder directly from the app.
- Settings: update currency formatting, date display, theme, and backup retention.
- Backups: timestamped copies with retention (3 recent + 3 historical by default).
- Config and themes are user-writable JSON in the data directory; defaults are auto-created on first run.

## Install / Run
The app only relies on the Python standard library (Tkinter included).

```bash
python app.py
```

## Data locations
- Config: `<data_dir>/settings.json`
- Weights: `<data_dir>/weights.json`
- Themes: `<data_dir>/themes.json`
- Items: `<data_dir>/data/items.csv`
- Money: `<data_dir>/data/money.csv`
- Backups: `<data_dir>/backups/`

## Building standalone binaries (PyInstaller)
```bash
# Linux/macOS
pyinstaller app.py --onefile --name finance_planner --add-data "config:config"

# Windows (note the path separator)
pyinstaller app.py --onefile --name finance_planner --add-data "config;config"
```

Binaries will appear under `dist/` (`finance_planner` on Linux/macOS, `finance_planner.exe` on Windows).

## CI artifacts
GitHub Actions workflow `.github/workflows/build.yml` builds standalone binaries for Linux and Windows using PyInstaller and uploads them as artifacts on each push/PR.
