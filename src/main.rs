mod backup;
mod cli;
mod config;
mod models;
mod scoring;
mod storage;

use anyhow::Result;
use clap::Parser;
use cli::{Cli, run};
use config::AppConfig;

fn main() -> Result<()> {
    let cfg = AppConfig::load()?;
    let cli = Cli::parse();
    run(cli, &cfg)
}
