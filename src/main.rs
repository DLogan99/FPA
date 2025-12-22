#![cfg_attr(target_os = "windows", windows_subsystem = "windows")]

mod backup;
mod config;
mod models;
mod scoring;
mod storage;
mod ui_app;

use anyhow::Result;
use config::AppConfig;

fn main() -> Result<()> {
    let cfg = AppConfig::load()?;
    ui_app::run_app(cfg)
}
