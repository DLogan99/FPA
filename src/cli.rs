use crate::backup::create_backup;
use crate::config::AppConfig;
use crate::models::{ItemRecord, MoneyRecord};
use crate::scoring::score_item;
use crate::storage::{read_items, read_money, write_items, write_money};
use anyhow::{Context, Result, anyhow};
use chrono::{DateTime, Local};
use clap::{Parser, Subcommand};
use colored::*;
use std::path::PathBuf;
use uuid::Uuid;

#[derive(Parser, Debug)]
#[command(name = "finance-planner")]
#[command(about = "Local-first finance planner (Rust)")]
pub struct Cli {
    #[command(subcommand)]
    pub command: Commands,
}

#[derive(Subcommand, Debug)]
pub enum Commands {
    Items(ItemsCmd),
    Money(MoneyCmd),
    Settings(SettingsCmd),
}

#[derive(Parser, Debug)]
pub struct ItemsCmd {
    #[command(subcommand)]
    pub cmd: ItemSub,
}

#[derive(Subcommand, Debug)]
pub enum ItemSub {
    Add {
        product: String,
        #[arg(long)]
        description: Option<String>,
        #[arg(long, default_value = "local")]
        location: String,
        #[arg(long, default_value = "")]
        reference: String,
        #[arg(long)]
        cost: f64,
        #[arg(long, default_value_t = 3)]
        urgency: i32,
        #[arg(long, default_value_t = 3)]
        value: i32,
        #[arg(long, default_value_t = 3)]
        price_comp: i32,
        #[arg(long, default_value_t = 3)]
        effect: i32,
        #[arg(long, default_value = "")]
        justification: String,
        #[arg(long, default_value = "none")]
        recurrence: String,
        #[arg(long)]
        date: Option<String>,
    },
    List,
    Delete {
        id: Uuid,
    },
    Import {
        path: PathBuf,
    },
}

#[derive(Parser, Debug)]
pub struct MoneyCmd {
    #[command(subcommand)]
    pub cmd: MoneySub,
}

#[derive(Subcommand, Debug)]
pub enum MoneySub {
    Add {
        #[arg(long)]
        entry_type: String,
        #[arg(long)]
        source_or_destination: String,
        #[arg(long)]
        amount: f64,
        #[arg(long, default_value = "")]
        notes: String,
        #[arg(long)]
        linked_item_id: Option<Uuid>,
        #[arg(long)]
        date: Option<String>,
    },
    List,
}

#[derive(Subcommand, Debug)]
pub enum SettingsCmd {
    Show,
}

pub fn run(cli: Cli, cfg: &AppConfig) -> Result<()> {
    match cli.command {
        Commands::Items(items_cmd) => handle_items(items_cmd, cfg),
        Commands::Money(money_cmd) => handle_money(money_cmd, cfg),
        Commands::Settings(settings_cmd) => handle_settings(settings_cmd, cfg),
    }
}

fn handle_items(cmd: ItemsCmd, cfg: &AppConfig) -> Result<()> {
    let mut items = read_items(&cfg.settings.paths.items_csv)?;
    match cmd.cmd {
        ItemSub::Add {
            product,
            description,
            location,
            reference,
            cost,
            urgency,
            value,
            price_comp,
            effect,
            justification,
            recurrence,
            date,
        } => {
            let dt = parse_date_opt(date, &cfg.settings.ui.date_format)?;
            let mut record = ItemRecord::new(
                dt,
                product,
                description.unwrap_or_default(),
                location,
                reference,
                cost,
                urgency,
                value,
                price_comp,
                effect,
                justification,
                recurrence,
            );
            let scored = score_item(&record, &cfg.weights);
            record.overall_score = Some(scored.overall);
            items.push(record);
            write_items(&cfg.settings.paths.items_csv, &items)?;
            create_backup(
                &cfg.settings.paths.items_csv,
                &cfg.settings.paths.backup_dir,
                &cfg.settings.backup,
            )?;
            println!("Item added.");
        }
        ItemSub::List => {
            if items.is_empty() {
                println!("No items found.");
            }
            items.sort_by_key(|i| i.date);
            for item in items {
                let overall = item.overall_score.unwrap_or(0.0);
                let mut overall_str = format!("{overall:.2}");
                if overall > 4.0 {
                    overall_str = overall_str.green().to_string();
                } else if overall < 2.5 {
                    overall_str = overall_str.red().to_string();
                }
                println!(
                    "{} | {} | ${:.2} | urg:{} | overall:{}",
                    item.product,
                    item.date.format(&cfg.settings.ui.date_format),
                    item.cost,
                    item.urgency,
                    overall_str
                );
            }
        }
        ItemSub::Delete { id } => {
            let start = items.len();
            items.retain(|i| i.id != id);
            if items.len() == start {
                return Err(anyhow!("Item not found"));
            }
            write_items(&cfg.settings.paths.items_csv, &items)?;
            println!("Item deleted.");
        }
        ItemSub::Import { path } => {
            let imported =
                read_items(&path).with_context(|| format!("Failed to read {}", path.display()))?;
            write_items(&cfg.settings.paths.items_csv, &imported)?;
            println!("Imported {} items.", imported.len());
        }
    }
    Ok(())
}

fn handle_money(cmd: MoneyCmd, cfg: &AppConfig) -> Result<()> {
    let mut money = read_money(&cfg.settings.paths.money_csv)?;
    match cmd.cmd {
        MoneySub::Add {
            entry_type,
            source_or_destination,
            amount,
            notes,
            linked_item_id,
            date,
        } => {
            let dt = parse_date_opt(date, &cfg.settings.ui.date_format)?;
            let record = MoneyRecord::new(
                dt,
                entry_type,
                source_or_destination,
                amount,
                notes,
                linked_item_id,
            );
            money.push(record);
            write_money(&cfg.settings.paths.money_csv, &money)?;
            create_backup(
                &cfg.settings.paths.money_csv,
                &cfg.settings.paths.backup_dir,
                &cfg.settings.backup,
            )?;
            println!("Money entry added.");
        }
        MoneySub::List => {
            if money.is_empty() {
                println!("No money entries found.");
            }
            money.sort_by_key(|m| m.date);
            for m in money {
                println!(
                    "{} | {} | ${:.2} | {}",
                    m.date.format(&cfg.settings.ui.date_format),
                    m.entry_type,
                    m.amount,
                    m.linked_item_id
                        .map(|id| id.to_string())
                        .unwrap_or_else(|| "unlinked".into())
                );
            }
        }
    }
    Ok(())
}

fn handle_settings(cmd: SettingsCmd, cfg: &AppConfig) -> Result<()> {
    match cmd {
        SettingsCmd::Show => {
            println!("Config directory: {}", cfg.base_dir.display());
            println!("Items CSV: {}", cfg.settings.paths.items_csv.display());
            println!("Money CSV: {}", cfg.settings.paths.money_csv.display());
            println!("Backup dir: {}", cfg.settings.paths.backup_dir.display());
            println!("Theme default: {}", cfg.settings.themes.default);
        }
    }
    Ok(())
}

fn parse_date_opt(input: Option<String>, fmt: &str) -> Result<DateTime<Local>> {
    if let Some(s) = input {
        let dt = Local
            .datetime_from_str(&s, fmt)
            .with_context(|| format!("Failed to parse date {s} with format {fmt}"))?;
        Ok(dt)
    } else {
        Ok(Local::now())
    }
}
