use crate::backup::create_backup;
use crate::cli::{Commands, ItemSub, ItemsCmd, MoneyCmd, MoneySub};
use crate::config::AppConfig;
use crate::models::{DATE_FMT, ItemRecord, MoneyRecord};
use crate::scoring::score_item;
use crate::storage::{read_items, read_money, write_items, write_money};
use chrono::{DateTime, Local, TimeZone};
use eframe::egui::{self, Align, Color32, Grid, RichText, ScrollArea, TextEdit};
use eframe::{App, Frame, NativeOptions};
use rfd::{FileDialog, MessageDialog, MessageDialogResult};
use uuid::Uuid;

pub fn run_app(cfg: AppConfig, cli: crate::cli::Cli) -> anyhow::Result<()> {
    if let Some(command) = cli.command {
        return crate::cli::run(
            crate::cli::Cli {
                command: Some(command),
            },
            &cfg,
        );
    }

    let app = PlannerApp::new(cfg)?;
    let native_options = NativeOptions::default();
    let result = eframe::run_native(
        "Finance Planner",
        native_options,
        Box::new(|_cc| Ok(Box::new(app))),
    );
    if let Err(err) = result {
        return Err(anyhow::anyhow!(err.to_string()));
    }
    Ok(())
}

struct PlannerApp {
    cfg: AppConfig,
    items: Vec<ItemRecord>,
    money: Vec<MoneyRecord>,
    log: String,
}

impl PlannerApp {
    fn new(cfg: AppConfig) -> anyhow::Result<Self> {
        let items = read_items(&cfg.settings.paths.items_csv)?;
        let money = read_money(&cfg.settings.paths.money_csv)?;
        Ok(Self {
            cfg,
            items,
            money,
            log: String::new(),
        })
    }

    fn add_log<S: AsRef<str>>(&mut self, msg: S) {
        self.log.push_str(msg.as_ref());
        self.log.push('\n');
    }
}

impl App for PlannerApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut Frame) {
        egui::TopBottomPanel::top("top").show(ctx, |ui| {
            ui.heading("Finance Planner (Rust)");
        });

        egui::SidePanel::left("side").show(ctx, |ui| {
            ui.vertical_centered(|ui| {
                ui.label("Items");
                if ui.button("Add Item").clicked() {
                    if let Some(item) = item_dialog(self.cfg.settings.ui.date_format.clone()) {
                        let mut record = item;
                        let score = score_item(&record, &self.cfg.weights);
                        record.overall_score = Some(score.overall);
                        self.items.push(record);
                        let _ = write_items(&self.cfg.settings.paths.items_csv, &self.items);
                        let _ = create_backup(
                            &self.cfg.settings.paths.items_csv,
                            &self.cfg.settings.paths.backup_dir,
                            &self.cfg.settings.backup,
                        );
                        self.add_log("Item added");
                    }
                }
                if ui.button("Delete Selected (ID)").clicked() {
                    if let Some(id) = prompt_uuid("Enter item UUID") {
                        let start = self.items.len();
                        self.items.retain(|i| i.id != id);
                        if self.items.len() != start {
                            let _ = create_backup(
                                &self.cfg.settings.paths.items_csv,
                                &self.cfg.settings.paths.backup_dir,
                                &self.cfg.settings.backup,
                            );
                            let _ = write_items(&self.cfg.settings.paths.items_csv, &self.items);
                            self.add_log("Item deleted");
                        }
                    }
                }
                if ui.button("Import Items CSV").clicked() {
                    if let Some(path) = FileDialog::new().add_filter("CSV", &["csv"]).pick_file() {
                        let _ = create_backup(
                            &self.cfg.settings.paths.items_csv,
                            &self.cfg.settings.paths.backup_dir,
                            &self.cfg.settings.backup,
                        );
                        match read_items(&path) {
                            Ok(imported) => {
                                self.items = imported;
                                let _ =
                                    write_items(&self.cfg.settings.paths.items_csv, &self.items);
                                self.add_log("Imported items");
                            }
                            Err(err) => self.add_log(format!("Import failed: {err}")),
                        }
                    }
                }
                ui.separator();
                ui.label("Money");
                if ui.button("Add Money").clicked() {
                    if let Some(entry) = money_dialog(self.cfg.settings.ui.date_format.clone()) {
                        self.money.push(entry);
                        let _ = write_money(&self.cfg.settings.paths.money_csv, &self.money);
                        let _ = create_backup(
                            &self.cfg.settings.paths.money_csv,
                            &self.cfg.settings.paths.backup_dir,
                            &self.cfg.settings.backup,
                        );
                        self.add_log("Money added");
                    }
                }
            });
        });

        egui::CentralPanel::default().show(ctx, |ui| {
            ui.heading("Items");
            ScrollArea::vertical().show(ui, |ui| {
                Grid::new("items_grid").striped(true).show(ui, |ui| {
                    ui.heading("Product");
                    ui.heading("Date");
                    ui.heading("Cost");
                    ui.heading("Urg");
                    ui.heading("Overall");
                    ui.end_row();
                    for item in &self.items {
                        ui.label(&item.product);
                        ui.label(item.date.format(DATE_FMT).to_string());
                        ui.label(format!("${:.2}", item.cost));
                        ui.label(item.urgency.to_string());
                        let overall = item.overall_score.unwrap_or(0.0);
                        let color = if overall > 4.0 {
                            Color32::GREEN
                        } else if overall < 2.5 {
                            Color32::RED
                        } else {
                            Color32::WHITE
                        };
                        ui.label(RichText::new(format!("{overall:.2}")).color(color));
                        ui.end_row();
                    }
                });
            });

            ui.separator();
            ui.heading("Money");
            ScrollArea::vertical().show(ui, |ui| {
                Grid::new("money_grid").striped(true).show(ui, |ui| {
                    ui.heading("Date");
                    ui.heading("Type");
                    ui.heading("Source/Dest");
                    ui.heading("Amount");
                    ui.heading("Linked Item");
                    ui.end_row();
                    for m in &self.money {
                        ui.label(m.date.format(DATE_FMT).to_string());
                        ui.label(&m.entry_type);
                        ui.label(&m.source_or_destination);
                        ui.label(format!("${:.2}", m.amount));
                        ui.label(
                            m.linked_item_id
                                .map(|id| id.to_string())
                                .unwrap_or_else(|| "".into()),
                        );
                        ui.end_row();
                    }
                });
            });

            ui.separator();
            ui.heading("Logs");
            ui.add(
                TextEdit::multiline(&mut self.log)
                    .code_editor()
                    .desired_rows(6),
            );
        });
    }
}

fn item_dialog(_date_fmt: String) -> Option<ItemRecord> {
    let _file = FileDialog::new();
    let product = MessageDialog::new()
        .set_title("Add item")
        .set_description("Enter product in the console")
        .set_buttons(rfd::MessageButtons::OkCancel)
        .show();
    if product != MessageDialogResult::Ok {
        return None;
    }
    // Stub: in a real app, use a proper modal form. Here we can't gather many fields interactively.
    let now = Local::now();
    Some(ItemRecord::new(
        now,
        "Untitled".into(),
        "".into(),
        "local".into(),
        "".into(),
        0.0,
        3,
        3,
        3,
        3,
        "".into(),
        "none".into(),
    ))
}

fn money_dialog(date_fmt: String) -> Option<MoneyRecord> {
    let _ = date_fmt;
    let now = Local::now();
    Some(MoneyRecord::new(
        now,
        "income".into(),
        "".into(),
        0.0,
        "".into(),
        None,
    ))
}

fn prompt_uuid(_label: &str) -> Option<Uuid> {
    None
}
