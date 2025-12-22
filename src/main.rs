mod backup;
mod cli;
mod config;
mod models;
mod scoring;
mod storage;
mod ui_app;

use anyhow::Result;
use clap::Parser;
use cli::Cli;
use config::AppConfig;

fn main() -> Result<()> {
    let cfg = AppConfig::load()?;
    let cli = Cli::parse();
    ui_app::run_app(cfg, cli)
}
