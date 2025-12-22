use anyhow::{Context, Result};
use directories::ProjectDirs;
use serde::{Deserialize, Serialize};
use std::fs;
use std::path::{Path, PathBuf};

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct PathsConfig {
    pub items_csv: PathBuf,
    pub money_csv: PathBuf,
    pub backup_dir: PathBuf,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct BackupConfig {
    pub keep_recent: usize,
    pub keep_historical: usize,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct UiConfig {
    pub date_format: String,
    pub currency_symbol: String,
    pub autosave: bool,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ThemesConfig {
    pub default: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Settings {
    pub paths: PathsConfig,
    pub backup: BackupConfig,
    pub themes: ThemesConfig,
    pub ui: UiConfig,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct WeightsConfig {
    pub weights: Weights,
    pub date_scoring: DateScoring,
    pub cost_bands: Vec<CostBand>,
    pub urgency_override: i32,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct Weights {
    pub date: f64,
    pub cost: f64,
    pub urgency: f64,
    pub value: f64,
    pub price_comp: f64,
    pub effect: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct DateScoring {
    pub recent_days: i64,
    pub mid_days: i64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct CostBand {
    pub max: Option<f64>,
    pub score: f64,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ThemeEntry {
    pub background: String,
    pub foreground: String,
    pub accent: String,
    pub muted: String,
    pub table: TableTheme,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct TableTheme {
    pub header_bg: String,
    pub header_fg: String,
    pub row_bg: String,
    pub alt_row_bg: String,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ThemesFile(pub serde_json::Map<String, serde_json::Value>);

#[derive(Debug, Clone)]
pub struct AppConfig {
    pub settings: Settings,
    pub weights: WeightsConfig,
    pub themes: serde_json::Value,
    pub base_dir: PathBuf,
}

impl AppConfig {
    pub fn load() -> Result<Self> {
        let dirs = project_dirs()?;
        let base_dir = dirs.data_dir().to_path_buf();
        fs::create_dir_all(&base_dir)?;

        let settings_path = base_dir.join("settings.json");
        let weights_path = base_dir.join("weights.json");
        let themes_path = base_dir.join("themes.json");

        let settings: Settings = load_or_write(&settings_path, default_settings(&base_dir))?;
        let weights: WeightsConfig = load_or_write(&weights_path, default_weights())?;
        let themes: serde_json::Value = load_or_write(&themes_path, default_themes())?;

        fs::create_dir_all(settings.paths.backup_dir.as_path())?;
        if let Some(parent) = settings.paths.items_csv.parent() {
            fs::create_dir_all(parent)?;
        }
        if let Some(parent) = settings.paths.money_csv.parent() {
            fs::create_dir_all(parent)?;
        }

        Ok(AppConfig {
            settings,
            weights,
            themes,
            base_dir,
        })
    }
}

fn load_or_write<T>(path: &Path, default: T) -> Result<T>
where
    T: Serialize + for<'de> Deserialize<'de>,
{
    if !path.exists() {
        let data = serde_json::to_string_pretty(&default)?;
        if let Some(parent) = path.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::write(path, data)?;
        return Ok(default);
    }
    let bytes =
        fs::read_to_string(path).with_context(|| format!("Failed to read {}", path.display()))?;
    let value = serde_json::from_str(&bytes)
        .with_context(|| format!("Failed to parse {}", path.display()))?;
    Ok(value)
}

fn project_dirs() -> Result<ProjectDirs> {
    ProjectDirs::from("com", "example", "finance_planner")
        .context("Unable to determine platform data directory")
}

fn default_settings(base_dir: &Path) -> Settings {
    let data_dir = base_dir.join("data");
    let backup_dir = base_dir.join("backups");
    Settings {
        paths: PathsConfig {
            items_csv: data_dir.join("items.csv"),
            money_csv: data_dir.join("money.csv"),
            backup_dir,
        },
        backup: BackupConfig {
            keep_recent: 3,
            keep_historical: 3,
        },
        themes: ThemesConfig {
            default: "light".into(),
        },
        ui: UiConfig {
            date_format: "%Y-%m-%d %H:%M".into(),
            currency_symbol: "$".into(),
            autosave: true,
        },
    }
}

fn default_weights() -> WeightsConfig {
    WeightsConfig {
        weights: Weights {
            date: 1.0,
            cost: 1.0,
            urgency: 1.0,
            value: 1.0,
            price_comp: 1.0,
            effect: 1.0,
        },
        date_scoring: DateScoring {
            recent_days: 7,
            mid_days: 30,
        },
        cost_bands: vec![
            CostBand {
                max: Some(50.0),
                score: 5.0,
            },
            CostBand {
                max: Some(150.0),
                score: 4.0,
            },
            CostBand {
                max: Some(400.0),
                score: 3.0,
            },
            CostBand {
                max: Some(800.0),
                score: 2.0,
            },
            CostBand {
                max: None,
                score: 1.0,
            },
        ],
        urgency_override: 5,
    }
}

fn default_themes() -> serde_json::Value {
    serde_json::json!({
        "light": {
            "background": "#f7f9fb",
            "foreground": "#0f172a",
            "accent": "#2563eb",
            "muted": "#94a3b8",
            "table": {
                "header_bg": "#e2e8f0",
                "header_fg": "#0f172a",
                "row_bg": "#ffffff",
                "alt_row_bg": "#f1f5f9"
            }
        },
        "dark": {
            "background": "#0b1220",
            "foreground": "#e2e8f0",
            "accent": "#60a5fa",
            "muted": "#94a3b8",
            "table": {
                "header_bg": "#1f2937",
                "header_fg": "#e5e7eb",
                "row_bg": "#111827",
                "alt_row_bg": "#0b1220"
            }
        },
        "toyota-retro": {
            "background": "#f8f1e7",
            "foreground": "#2d2a32",
            "accent": "#c1121f",
            "muted": "#7a6f6f",
            "table": {
                "header_bg": "#e0d3c2",
                "header_fg": "#2d2a32",
                "row_bg": "#fff8ef",
                "alt_row_bg": "#f3e8d5"
            }
        },
        "openai-inspired": {
            "background": "#0d1117",
            "foreground": "#c9d1d9",
            "accent": "#3fb950",
            "muted": "#8b949e",
            "table": {
                "header_bg": "#161b22",
                "header_fg": "#c9d1d9",
                "row_bg": "#0d1117",
                "alt_row_bg": "#111827"
            }
        }
    })
}
