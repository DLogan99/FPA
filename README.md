# Finance Planner (Rust rewrite)

Local-first finance planner rewritten in Rust. Stores data in CSV and configurable JSON files under your OS data directory (e.g., `%APPDATA%/finance_planner` on Windows or `~/.local/share/finance_planner` on Linux).

## Features
- Purchases/Items: add, list, delete, import from CSV. Scores computed via configurable weights.
- Money: add and list entries, optionally link to items by ID.
- Settings: show paths and current theme name.
- Backups: timestamped copies with retention (3 recent + 3 historical by default).
- Config and themes are user-writable JSON in the data directory; defaults are auto-created on first run.

## Install / Run
```bash
cargo run -- items add --product "Widget" --cost 25 --urgency 3 --value 4 --price-comp 3 --effect 3 --justification "Need"

cargo run -- items list

cargo run -- money add --entry-type expense --source-or-destination "Store" --amount 25

cargo run -- settings show
```

## Data locations
- Config: `<data_dir>/settings.json`
- Weights: `<data_dir>/weights.json`
- Themes: `<data_dir>/themes.json`
- Items: `<data_dir>/data/items.csv`
- Money: `<data_dir>/data/money.csv`
- Backups: `<data_dir>/backups/`

## Building
```bash
cargo build --release
```

Artifacts will be in `target/release/finance_planner` (Linux) or `target\release\finance_planner.exe` (Windows).

## CI artifacts
GitHub Actions workflow `.github/workflows/build.yml` builds release binaries for Linux and Windows and uploads them as artifacts on each push/PR (including this `rust-rewrite` branch). Download them from the workflow run's Artifacts section.
