use crate::models::{DATE_FMT, ItemRecord, MoneyRecord};
use anyhow::{Context, Result};
use chrono::{DateTime, Local, TimeZone};
use csv::{ReaderBuilder, WriterBuilder};
use fs2::FileExt;
use std::fs::{File, OpenOptions};
use std::path::Path;
use uuid::Uuid;

pub fn read_items(path: &Path) -> Result<Vec<ItemRecord>> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let file = File::open(path)?;
    file.lock_shared()?;
    let mut reader = ReaderBuilder::new().from_reader(&file);
    let mut items = Vec::new();
    for result in reader.deserialize::<CsvItem>() {
        let csv_item = result?;
        items.push(csv_item.into_record());
    }
    file.unlock()?;
    Ok(items)
}

pub fn write_items(path: &Path, items: &[ItemRecord]) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(path)?;
    file.lock_exclusive()?;
    file.set_len(0)?;
    let mut writer = WriterBuilder::new().has_headers(true).from_writer(&file);
    for item in items {
        writer.serialize(CsvItem::from(item))?;
    }
    writer.flush()?;
    file.unlock()?;
    Ok(())
}

pub fn read_money(path: &Path) -> Result<Vec<MoneyRecord>> {
    if !path.exists() {
        return Ok(Vec::new());
    }
    let file = File::open(path)?;
    file.lock_shared()?;
    let mut reader = ReaderBuilder::new().from_reader(&file);
    let mut entries = Vec::new();
    for result in reader.deserialize::<CsvMoney>() {
        let csv_entry = result?;
        entries.push(csv_entry.into_record());
    }
    file.unlock()?;
    Ok(entries)
}

pub fn write_money(path: &Path, entries: &[MoneyRecord]) -> Result<()> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = OpenOptions::new()
        .read(true)
        .write(true)
        .create(true)
        .open(path)?;
    file.lock_exclusive()?;
    file.set_len(0)?;
    let mut writer = WriterBuilder::new().has_headers(true).from_writer(&file);
    for entry in entries {
        writer.serialize(CsvMoney::from(entry))?;
    }
    writer.flush()?;
    file.unlock()?;
    Ok(())
}

#[derive(serde::Deserialize, serde::Serialize)]
struct CsvItem {
    id: Uuid,
    date: String,
    product: String,
    description: String,
    location: String,
    reference: String,
    cost: f64,
    urgency: i32,
    value: i32,
    price_comp: i32,
    effect: i32,
    justification: String,
    recurrence: String,
    overall_score: Option<f64>,
}

impl CsvItem {
    fn into_record(self) -> ItemRecord {
        let date = Local
            .datetime_from_str(&self.date, DATE_FMT)
            .unwrap_or_else(|_| Local::now());
        ItemRecord {
            id: self.id,
            date,
            product: self.product,
            description: self.description,
            location: self.location,
            reference: self.reference,
            cost: self.cost,
            urgency: self.urgency,
            value: self.value,
            price_comp: self.price_comp,
            effect: self.effect,
            justification: self.justification,
            recurrence: self.recurrence,
            overall_score: self.overall_score,
        }
    }
}

impl From<&ItemRecord> for CsvItem {
    fn from(item: &ItemRecord) -> Self {
        CsvItem {
            id: item.id,
            date: item.date.format(DATE_FMT).to_string(),
            product: item.product.clone(),
            description: item.description.clone(),
            location: item.location.clone(),
            reference: item.reference.clone(),
            cost: item.cost,
            urgency: item.urgency,
            value: item.value,
            price_comp: item.price_comp,
            effect: item.effect,
            justification: item.justification.clone(),
            recurrence: item.recurrence.clone(),
            overall_score: item.overall_score,
        }
    }
}

#[derive(serde::Deserialize, serde::Serialize)]
struct CsvMoney {
    id: Uuid,
    date: String,
    entry_type: String,
    source_or_destination: String,
    amount: f64,
    notes: String,
    linked_item_id: Option<Uuid>,
}

impl CsvMoney {
    fn into_record(self) -> MoneyRecord {
        let date = Local
            .datetime_from_str(&self.date, DATE_FMT)
            .unwrap_or_else(|_| Local::now());
        MoneyRecord {
            id: self.id,
            date,
            entry_type: self.entry_type,
            source_or_destination: self.source_or_destination,
            amount: self.amount,
            notes: self.notes,
            linked_item_id: self.linked_item_id,
        }
    }
}

impl From<&MoneyRecord> for CsvMoney {
    fn from(entry: &MoneyRecord) -> Self {
        CsvMoney {
            id: entry.id,
            date: entry.date.format(DATE_FMT).to_string(),
            entry_type: entry.entry_type.clone(),
            source_or_destination: entry.source_or_destination.clone(),
            amount: entry.amount,
            notes: entry.notes.clone(),
            linked_item_id: entry.linked_item_id,
        }
    }
}
