use crate::backup::create_backup;
use crate::config::AppConfig;
use crate::models::{DATE_FMT, ItemRecord, MoneyRecord};
use crate::scoring::score_item;
use crate::storage::{read_items, read_money, write_items, write_money};
use anyhow::{Result, anyhow};
use chrono::{DateTime, Local, NaiveDateTime, TimeZone};
use eframe::egui::{self, Color32, ComboBox, Grid, RichText, ScrollArea, TextEdit};
use eframe::{App, Frame, NativeOptions};
use rfd::FileDialog;
use uuid::Uuid;

pub fn run_app(cfg: AppConfig) -> Result<()> {
    let app = PlannerApp::new(cfg)?;
    let native_options = NativeOptions::default();
    eframe::run_native(
        "Finance Planner",
        native_options,
        Box::new(|_cc| Ok(Box::new(app))),
    )
    .map_err(|e| anyhow!(e.to_string()))
}

struct PlannerApp {
    cfg: AppConfig,
    items: Vec<ItemRecord>,
    money: Vec<MoneyRecord>,
    log: String,
    new_item: ItemForm,
    new_money: MoneyForm,
    delete_id: String,
}

impl PlannerApp {
    fn new(cfg: AppConfig) -> Result<Self> {
        let items = read_items(&cfg.settings.paths.items_csv)?;
        let money = read_money(&cfg.settings.paths.money_csv)?;
        Ok(Self {
            cfg,
            items,
            money,
            log: String::new(),
            new_item: ItemForm::default(),
            new_money: MoneyForm::default(),
            delete_id: String::new(),
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
            ui.heading("Finance Planner (Rust UI)");
        });

        egui::SidePanel::left("side").show(ctx, |ui| {
            ui.heading("Item");
            self.new_item.ui(ui, &self.items);
            if ui.button("Add Item").clicked() {
                match self.new_item.to_record(&self.cfg.settings.ui.date_format) {
                    Ok(mut record) => {
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
                        self.new_item = ItemForm::default();
                    }
                    Err(err) => self.add_log(format!("Item add failed: {err}")),
                }
            }
            ui.horizontal(|ui| {
                ui.label("Delete by UUID:");
                ui.text_edit_singleline(&mut self.delete_id);
            });
            if ui.button("Delete").clicked() {
                if let Ok(id) = Uuid::parse_str(self.delete_id.trim()) {
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
                    } else {
                        self.add_log("Item not found");
                    }
                } else {
                    self.add_log("Invalid UUID");
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
                            let _ = write_items(&self.cfg.settings.paths.items_csv, &self.items);
                            self.add_log("Imported items");
                        }
                        Err(err) => self.add_log(format!("Import failed: {err}")),
                    }
                }
            }

            ui.separator();
            ui.heading("Money");
            self.new_money.ui(ui, &self.items);
            if ui.button("Add Money").clicked() {
                match self.new_money.to_record(&self.cfg.settings.ui.date_format) {
                    Ok(entry) => {
                        self.money.push(entry);
                        let _ = write_money(&self.cfg.settings.paths.money_csv, &self.money);
                        let _ = create_backup(
                            &self.cfg.settings.paths.money_csv,
                            &self.cfg.settings.paths.backup_dir,
                            &self.cfg.settings.backup,
                        );
                        self.add_log("Money added");
                        self.new_money = MoneyForm::default();
                    }
                    Err(err) => self.add_log(format!("Money add failed: {err}")),
                }
            }
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
                        let linked_name = m
                            .linked_item_id
                            .and_then(|id| self.items.iter().find(|i| i.id == id))
                            .map(|i| i.product.clone())
                            .unwrap_or_default();
                        ui.label(linked_name);
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

#[derive(Default, Clone)]
struct ItemForm {
    product: String,
    description: String,
    location: String,
    reference: String,
    cost: String,
    urgency: String,
    value: String,
    price_comp: String,
    effect: String,
    justification: String,
    recurrence: String,
    date: String,
    linked_item: Option<Uuid>,
}

impl ItemForm {
    fn ui(&mut self, ui: &mut egui::Ui, items: &[ItemRecord]) {
        ui.add(TextEdit::singleline(&mut self.product).hint_text("Product"));
        ui.add(TextEdit::singleline(&mut self.description).hint_text("Description"));
        ui.add(TextEdit::singleline(&mut self.location).hint_text("Location"));
        ui.add(TextEdit::singleline(&mut self.reference).hint_text("Reference URL"));
        ui.add(TextEdit::singleline(&mut self.cost).hint_text("Cost"));
        ui.add(TextEdit::singleline(&mut self.justification).hint_text("Justification"));
        ui.add(TextEdit::singleline(&mut self.date).hint_text("Date (YYYY-MM-DD HH:MM)"));

        ui.horizontal(|ui| {
            ui.label("Urgency");
            ui.add(TextEdit::singleline(&mut self.urgency));
            ui.label("Value");
            ui.add(TextEdit::singleline(&mut self.value));
        });
        ui.horizontal(|ui| {
            ui.label("Price vs Similar");
            ui.add(TextEdit::singleline(&mut self.price_comp));
            ui.label("Effect");
            ui.add(TextEdit::singleline(&mut self.effect));
        });
        ComboBox::from_label("Recurrence")
            .selected_text(if self.recurrence.is_empty() {
                "none".to_string()
            } else {
                self.recurrence.clone()
            })
            .show_ui(ui, |ui| {
                for opt in [
                    "none",
                    "once",
                    "weekly",
                    "biweekly",
                    "monthly",
                    "quarterly",
                    "yearly",
                ] {
                    ui.selectable_value(&mut self.recurrence, opt.to_string(), opt);
                }
            });
    }

    fn to_record(&self, fmt: &str) -> Result<ItemRecord> {
        let date = if self.date.trim().is_empty() {
            Local::now()
        } else {
            let naive = NaiveDateTime::parse_from_str(self.date.trim(), fmt)
                .map_err(|e| anyhow!("Invalid date: {e}"))?;
            Local
                .from_local_datetime(&naive)
                .single()
                .unwrap_or_else(|| Local::now())
        };
        let cost = self
            .cost
            .trim()
            .parse::<f64>()
            .map_err(|e| anyhow!("Invalid cost: {e}"))?;
        let urgency = parse_int(&self.urgency, "urgency")?;
        let value = parse_int(&self.value, "value")?;
        let price_comp = parse_int(&self.price_comp, "price_comp")?;
        let effect = parse_int(&self.effect, "effect")?;
        Ok(ItemRecord::new(
            date,
            self.product.clone(),
            self.description.clone(),
            self.location.clone(),
            self.reference.clone(),
            cost,
            urgency,
            value,
            price_comp,
            effect,
            self.justification.clone(),
            if self.recurrence.is_empty() {
                "none".into()
            } else {
                self.recurrence.clone()
            },
        ))
    }
}

#[derive(Default, Clone)]
struct MoneyForm {
    entry_type: String,
    source_or_destination: String,
    amount: String,
    notes: String,
    linked_item_id: Option<Uuid>,
    date: String,
}

impl MoneyForm {
    fn ui(&mut self, ui: &mut egui::Ui, items: &[ItemRecord]) {
        ui.add(TextEdit::singleline(&mut self.entry_type).hint_text("Type (income/expense)"));
        ui.add(
            TextEdit::singleline(&mut self.source_or_destination)
                .hint_text("Source or destination"),
        );
        ui.add(TextEdit::singleline(&mut self.amount).hint_text("Amount"));
        ui.add(TextEdit::singleline(&mut self.notes).hint_text("Notes"));
        ui.add(TextEdit::singleline(&mut self.date).hint_text("Date (YYYY-MM-DD HH:MM)"));

        ComboBox::from_label("Link to item")
            .selected_text(
                self.linked_item_id
                    .and_then(|id| items.iter().find(|i| i.id == id))
                    .map(|i| i.product.clone())
                    .unwrap_or_else(|| "None".into()),
            )
            .show_ui(ui, |ui| {
                ui.selectable_value(&mut self.linked_item_id, None, "None");
                for item in items {
                    ui.selectable_value(&mut self.linked_item_id, Some(item.id), &item.product);
                }
            });
    }

    fn to_record(&self, fmt: &str) -> Result<MoneyRecord> {
        let date = if self.date.trim().is_empty() {
            Local::now()
        } else {
            let naive = NaiveDateTime::parse_from_str(self.date.trim(), fmt)
                .map_err(|e| anyhow!("Invalid date: {e}"))?;
            Local
                .from_local_datetime(&naive)
                .single()
                .unwrap_or_else(|| Local::now())
        };
        let amount = self
            .amount
            .trim()
            .parse::<f64>()
            .map_err(|e| anyhow!("Invalid amount: {e}"))?;
        Ok(MoneyRecord::new(
            date,
            if self.entry_type.is_empty() {
                "income".into()
            } else {
                self.entry_type.clone()
            },
            self.source_or_destination.clone(),
            amount,
            self.notes.clone(),
            self.linked_item_id,
        ))
    }
}

fn parse_int(text: &str, field: &str) -> Result<i32> {
    text.trim()
        .parse::<i32>()
        .map_err(|e| anyhow!("Invalid {field}: {e}"))
}
