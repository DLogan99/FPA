use crate::backup::create_backup;
use crate::config::AppConfig;
use crate::models::{DATE_FMT, ItemRecord, MoneyRecord};
use crate::scoring::score_item;
use crate::storage::{read_items, read_money, write_items, write_money};
use anyhow::{Result, anyhow};
use chrono::{DateTime, Local, NaiveDate, NaiveDateTime, NaiveTime, Timelike};
use eframe::egui::DragValue;
use eframe::egui::ViewportBuilder;
use eframe::egui::{self, Color32, ComboBox, Grid, RichText, ScrollArea, TextEdit, TopBottomPanel};
use eframe::egui::{CentralPanel, Context, SidePanel};
use eframe::{App, Frame, NativeOptions};
use egui_extras::DatePickerButton;
use rfd::FileDialog;
use uuid::Uuid;

pub fn run_app(cfg: AppConfig) -> Result<()> {
    let app = PlannerApp::new(cfg)?;
    let native_options = NativeOptions {
        viewport: ViewportBuilder::default().with_decorations(true),
        ..Default::default()
    };
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
    tab: Tab,
    selected_item: Option<Uuid>,
    selected_money: Option<Uuid>,
    show_item_modal: bool,
    show_money_modal: bool,
    item_modal_mode: ModalMode,
    money_modal_mode: ModalMode,
    item_form: ItemForm,
    money_form: MoneyForm,
    show_settings: bool,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum Tab {
    Items,
    Money,
}

#[derive(Clone, Copy, PartialEq, Eq)]
enum ModalMode {
    Add,
    Edit(Uuid),
    View,
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
            tab: Tab::Items,
            selected_item: None,
            selected_money: None,
            show_item_modal: false,
            show_money_modal: false,
            item_modal_mode: ModalMode::Add,
            money_modal_mode: ModalMode::Add,
            item_form: ItemForm::default_with_now(&cfg.settings.ui.date_format),
            money_form: MoneyForm::default_with_now(&cfg.settings.ui.date_format),
            show_settings: false,
        })
    }

    fn add_log<S: AsRef<str>>(&mut self, msg: S) {
        self.log.push_str(msg.as_ref());
        self.log.push('\n');
    }
}

impl App for PlannerApp {
    fn update(&mut self, ctx: &Context, _frame: &mut Frame) {
        TopBottomPanel::top("top").show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.heading("Finance Planner (Rust UI)");
                ui.menu_button("Settings", |ui| {
                    if ui.button("Open Settings").clicked() {
                        self.show_settings = true;
                        ui.close_menu();
                    }
                });
            });
        });

        SidePanel::left("nav").show(ctx, |ui| {
            ui.heading("Tabs");
            if ui
                .selectable_label(self.tab == Tab::Items, "Items")
                .clicked()
            {
                self.tab = Tab::Items;
            }
            if ui
                .selectable_label(self.tab == Tab::Money, "Money")
                .clicked()
            {
                self.tab = Tab::Money;
            }
            ui.separator();
            if ui.button("Add Item").clicked() {
                self.item_modal_mode = ModalMode::Add;
                self.item_form = ItemForm::default_with_now(&self.cfg.settings.ui.date_format);
                self.show_item_modal = true;
            }
            if ui.button("Edit Item").clicked() {
                if let Some(id) = self.selected_item {
                    if let Some(item) = self.items.iter().find(|i| i.id == id) {
                        self.item_form =
                            ItemForm::from_record(item, &self.cfg.settings.ui.date_format);
                        self.item_modal_mode = ModalMode::Edit(id);
                        self.show_item_modal = true;
                    }
                }
            }
            if ui.button("View Item").clicked() {
                if let Some(id) = self.selected_item {
                    if let Some(item) = self.items.iter().find(|i| i.id == id) {
                        self.item_form =
                            ItemForm::from_record(item, &self.cfg.settings.ui.date_format);
                        self.item_modal_mode = ModalMode::View;
                        self.show_item_modal = true;
                    }
                }
            }
            if ui.button("Delete Item").clicked() {
                if let Some(id) = self.selected_item {
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
                        self.selected_item = None;
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
                            let _ = write_items(&self.cfg.settings.paths.items_csv, &self.items);
                            self.add_log("Imported items");
                        }
                        Err(err) => self.add_log(format!("Import failed: {err}")),
                    }
                }
            }

            ui.separator();
            if ui.button("Add Money").clicked() {
                self.money_modal_mode = ModalMode::Add;
                self.money_form = MoneyForm::default_with_now(&self.cfg.settings.ui.date_format);
                self.show_money_modal = true;
            }
            if ui.button("Edit Money").clicked() {
                if let Some(id) = self.selected_money {
                    if let Some(entry) = self.money.iter().find(|m| m.id == id) {
                        self.money_form =
                            MoneyForm::from_record(entry, &self.cfg.settings.ui.date_format);
                        self.money_modal_mode = ModalMode::Edit(id);
                        self.show_money_modal = true;
                    }
                }
            }
            if ui.button("View Money").clicked() {
                if let Some(id) = self.selected_money {
                    if let Some(entry) = self.money.iter().find(|m| m.id == id) {
                        self.money_form =
                            MoneyForm::from_record(entry, &self.cfg.settings.ui.date_format);
                        self.money_modal_mode = ModalMode::View;
                        self.show_money_modal = true;
                    }
                }
            }
            if ui.button("Delete Money").clicked() {
                if let Some(id) = self.selected_money {
                    let start = self.money.len();
                    self.money.retain(|m| m.id != id);
                    if self.money.len() != start {
                        let _ = create_backup(
                            &self.cfg.settings.paths.money_csv,
                            &self.cfg.settings.paths.backup_dir,
                            &self.cfg.settings.backup,
                        );
                        let _ = write_money(&self.cfg.settings.paths.money_csv, &self.money);
                        self.add_log("Money deleted");
                        self.selected_money = None;
                    }
                }
            }
        });

        CentralPanel::default().show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.selectable_value(&mut self.tab, Tab::Items, "Items");
                ui.selectable_value(&mut self.tab, Tab::Money, "Money");
            });

            ScrollArea::vertical().show(ui, |ui| match self.tab {
                Tab::Items => {
                    Grid::new("items_grid").striped(true).show(ui, |ui| {
                        ui.heading("Product");
                        ui.heading("Date");
                        ui.heading("Cost");
                        ui.heading("Urg");
                        ui.heading("Overall");
                        ui.end_row();
                        for item in &self.items {
                            let selected = Some(item.id) == self.selected_item;
                            if ui.selectable_label(selected, &item.product).clicked() {
                                self.selected_item = Some(item.id);
                            }
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
                }
                Tab::Money => {
                    Grid::new("money_grid").striped(true).show(ui, |ui| {
                        ui.heading("Date");
                        ui.heading("Type");
                        ui.heading("Source/Dest");
                        ui.heading("Amount");
                        ui.heading("Linked Item");
                        ui.end_row();
                        for m in &self.money {
                            let selected = Some(m.id) == self.selected_money;
                            if ui
                                .selectable_label(selected, m.date.format(DATE_FMT).to_string())
                                .clicked()
                            {
                                self.selected_money = Some(m.id);
                            }
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
                }
            });

            ui.separator();
            ui.heading("Logs");
            ui.add(
                TextEdit::multiline(&mut self.log)
                    .code_editor()
                    .desired_rows(6),
            );
        });

        if self.show_item_modal {
            let title = match self.item_modal_mode {
                ModalMode::Add => "Add Item",
                ModalMode::Edit(_) => "Edit Item",
                ModalMode::View => "View Item",
            };
            egui::Window::new(title)
                .collapsible(false)
                .resizable(true)
                .show(ctx, |ui| {
                    self.item_form.ui(ui, &self.items);
                    if matches!(self.item_modal_mode, ModalMode::View) {
                        if ui.button("Close").clicked() {
                            self.show_item_modal = false;
                        }
                        return;
                    }
                    if ui.button("Save").clicked() {
                        match self.item_form.to_record(&self.cfg.settings.ui.date_format) {
                            Ok(mut record) => {
                                let score = score_item(&record, &self.cfg.weights);
                                record.overall_score = Some(score.overall);
                                match self.item_modal_mode {
                                    ModalMode::Add => self.items.push(record),
                                    ModalMode::Edit(id) => {
                                        if let Some(pos) =
                                            self.items.iter().position(|i| i.id == id)
                                        {
                                            record.id = id;
                                            self.items[pos] = record;
                                        }
                                    }
                                    ModalMode::View => {}
                                }
                                let _ =
                                    write_items(&self.cfg.settings.paths.items_csv, &self.items);
                                let _ = create_backup(
                                    &self.cfg.settings.paths.items_csv,
                                    &self.cfg.settings.paths.backup_dir,
                                    &self.cfg.settings.backup,
                                );
                                self.show_item_modal = false;
                            }
                            Err(err) => self.add_log(format!("Save failed: {err}")),
                        }
                    }
                    if ui.button("Cancel").clicked() {
                        self.show_item_modal = false;
                    }
                });
        }

        if self.show_money_modal {
            let title = match self.money_modal_mode {
                ModalMode::Add => "Add Money",
                ModalMode::Edit(_) => "Edit Money",
                ModalMode::View => "View Money",
            };
            egui::Window::new(title)
                .collapsible(false)
                .resizable(true)
                .show(ctx, |ui| {
                    self.money_form.ui(ui, &self.items);
                    if matches!(self.money_modal_mode, ModalMode::View) {
                        if ui.button("Close").clicked() {
                            self.show_money_modal = false;
                        }
                        return;
                    }
                    if ui.button("Save").clicked() {
                        match self.money_form.to_record(&self.cfg.settings.ui.date_format) {
                            Ok(mut record) => {
                                match self.money_modal_mode {
                                    ModalMode::Add => self.money.push(record),
                                    ModalMode::Edit(id) => {
                                        if let Some(pos) =
                                            self.money.iter().position(|m| m.id == id)
                                        {
                                            record.id = id;
                                            self.money[pos] = record;
                                        }
                                    }
                                    ModalMode::View => {}
                                }
                                let _ =
                                    write_money(&self.cfg.settings.paths.money_csv, &self.money);
                                let _ = create_backup(
                                    &self.cfg.settings.paths.money_csv,
                                    &self.cfg.settings.paths.backup_dir,
                                    &self.cfg.settings.backup,
                                );
                                self.show_money_modal = false;
                            }
                            Err(err) => self.add_log(format!("Save failed: {err}")),
                        }
                    }
                    if ui.button("Cancel").clicked() {
                        self.show_money_modal = false;
                    }
                });
        }

        if self.show_settings {
            egui::Window::new("Settings")
                .collapsible(false)
                .resizable(true)
                .show(ctx, |ui| {
                    ui.label(format!("Config directory: {}", self.cfg.base_dir.display()));
                    ui.label(format!(
                        "Items CSV: {}",
                        self.cfg.settings.paths.items_csv.display()
                    ));
                    ui.label(format!(
                        "Money CSV: {}",
                        self.cfg.settings.paths.money_csv.display()
                    ));
                    ui.label(format!(
                        "Backup dir: {}",
                        self.cfg.settings.paths.backup_dir.display()
                    ));
                    if ui.button("Close").clicked() {
                        self.show_settings = false;
                    }
                });
        }
    }
}

#[derive(Clone, Default)]
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
    date: NaiveDate,
    hour: u32,
    minute: u32,
}

impl ItemForm {
    fn default_with_now(_fmt: &str) -> Self {
        let now = Local::now();
        Self {
            date: now.date_naive(),
            hour: now.hour(),
            minute: now.minute(),
            ..Default::default()
        }
    }

    fn from_record(rec: &ItemRecord, _fmt: &str) -> Self {
        Self {
            product: rec.product.clone(),
            description: rec.description.clone(),
            location: rec.location.clone(),
            reference: rec.reference.clone(),
            cost: rec.cost.to_string(),
            urgency: rec.urgency.to_string(),
            value: rec.value.to_string(),
            price_comp: rec.price_comp.to_string(),
            effect: rec.effect.to_string(),
            justification: rec.justification.clone(),
            recurrence: rec.recurrence.clone(),
            date: rec.date.date_naive(),
            hour: rec.date.hour(),
            minute: rec.date.minute(),
        }
    }

    fn ui(&mut self, ui: &mut egui::Ui, _items: &[ItemRecord]) {
        ui.horizontal(|ui| {
            ui.label("Date");
            ui.label(self.combined_datetime().format(DATE_FMT).to_string());
            if DatePickerButton::new(&mut self.date).show(ui).changed() {
                // date updated
            }
            ui.add(DragValue::new(&mut self.hour).clamp_range(0..=23));
            ui.add(DragValue::new(&mut self.minute).clamp_range(0..=59));
        });
        ui.add(TextEdit::singleline(&mut self.product).hint_text("Product"));
        ui.add(TextEdit::singleline(&mut self.description).hint_text("Description"));
        ui.add(TextEdit::singleline(&mut self.location).hint_text("Location"));
        ui.add(TextEdit::singleline(&mut self.reference).hint_text("Reference URL"));
        ui.add(TextEdit::singleline(&mut self.cost).hint_text("Cost"));
        ui.add(TextEdit::singleline(&mut self.justification).hint_text("Justification"));

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

    fn combined_datetime(&self) -> DateTime<Local> {
        let time = NaiveTime::from_hms_opt(self.hour, self.minute, 0)
            .unwrap_or_else(|| NaiveTime::from_hms_opt(0, 0, 0).unwrap());
        let naive = NaiveDateTime::new(self.date, time);
        Local
            .from_local_datetime(&naive)
            .single()
            .unwrap_or_else(|| Local::now())
    }

    fn to_record(&self, _fmt: &str) -> Result<ItemRecord> {
        let date = self.combined_datetime();
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

#[derive(Clone, Default)]
struct MoneyForm {
    entry_type: String,
    source_or_destination: String,
    amount: String,
    notes: String,
    linked_item_id: Option<Uuid>,
    date: NaiveDate,
    hour: u32,
    minute: u32,
}

impl MoneyForm {
    fn default_with_now(_fmt: &str) -> Self {
        let now = Local::now();
        Self {
            entry_type: "income".into(),
            date: now.date_naive(),
            hour: now.hour(),
            minute: now.minute(),
            ..Default::default()
        }
    }

    fn from_record(rec: &MoneyRecord, _fmt: &str) -> Self {
        Self {
            entry_type: rec.entry_type.clone(),
            source_or_destination: rec.source_or_destination.clone(),
            amount: rec.amount.to_string(),
            notes: rec.notes.clone(),
            linked_item_id: rec.linked_item_id,
            date: rec.date.date_naive(),
            hour: rec.date.hour(),
            minute: rec.date.minute(),
        }
    }

    fn ui(&mut self, ui: &mut egui::Ui, items: &[ItemRecord]) {
        ui.horizontal(|ui| {
            ui.label("Date");
            ui.label(self.combined_datetime().format(DATE_FMT).to_string());
            if DatePickerButton::new(&mut self.date).show(ui).changed() {}
            ui.add(DragValue::new(&mut self.hour).clamp_range(0..=23));
            ui.add(DragValue::new(&mut self.minute).clamp_range(0..=59));
        });
        ui.add(TextEdit::singleline(&mut self.entry_type).hint_text("Type (income/expense)"));
        ui.add(
            TextEdit::singleline(&mut self.source_or_destination)
                .hint_text("Source or destination"),
        );
        ui.add(TextEdit::singleline(&mut self.amount).hint_text("Amount"));
        ui.add(TextEdit::singleline(&mut self.notes).hint_text("Notes"));

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

    fn combined_datetime(&self) -> DateTime<Local> {
        let time = NaiveTime::from_hms_opt(self.hour, self.minute, 0)
            .unwrap_or_else(|| NaiveTime::from_hms_opt(0, 0, 0).unwrap());
        let naive = NaiveDateTime::new(self.date, time);
        Local
            .from_local_datetime(&naive)
            .single()
            .unwrap_or_else(|| Local::now())
    }

    fn to_record(&self, _fmt: &str) -> Result<MoneyRecord> {
        let date = self.combined_datetime();
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
