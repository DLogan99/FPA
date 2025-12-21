# Finance Planner App

Local-first finance planning desktop app (Tkinter) for purchases and money tracking. Data stays in CSV files; scoring weights and themes are configurable.

## Running

```bash
python app.py
```

Requires Python 3.10+ (standard library only).

## Data & Config
- Purchases/items: `data/items.csv`
- Money entries: `data/money.csv`
- Settings: `config/settings.json`
- Weights & scoring: `config/weights.json`
- Themes: `config/themes.json`
- Backups: `backups/`

## Views
- **Purchases**: Excel-style table of planned/recurring purchases with scores; add/edit/view items.
- **Money**: Income/expense table; add/edit entries; optional link to items by ID.
- **Settings**: Theme picker (light, dark, Toyota-retro, OpenAI-inspired), autosave toggle, manual backup.

## Scoring
- Separated in `scoring/scoring.py`. Date scoring uses inclusive thresholds (recent/mid); urgency 5 forces date to highest. Cost bands and weights are fully editable in `config/weights.json`.

## Backup policy
Default: keep 3 most recent backups + 3 spaced historical snapshots per file (configurable in `config/settings.json`).

## Stored ideas
See `stored_ideas.md` for future-scope items you requested to keep on file.

## Downloading prebuilt binaries (CI artifacts)
- GitHub Actions workflow: `.github/workflows/build.yml` builds Windows (`finance-planner-windows.exe`) and Linux (`finance-planner-linux`) binaries via PyInstaller.
- After a push/PR, open the workflow run in GitHub Actions and download the artifact for your OS.
