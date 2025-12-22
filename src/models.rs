use chrono::{DateTime, Local};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub const DATE_FMT: &str = "%Y-%m-%d %H:%M";

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct ItemRecord {
    pub id: Uuid,
    pub date: DateTime<Local>,
    pub product: String,
    pub description: String,
    pub location: String,
    pub reference: String,
    pub cost: f64,
    pub urgency: i32,
    pub value: i32,
    pub price_comp: i32,
    pub effect: i32,
    pub justification: String,
    pub recurrence: String,
    pub overall_score: Option<f64>,
}

#[derive(Debug, Serialize, Deserialize, Clone)]
pub struct MoneyRecord {
    pub id: Uuid,
    pub date: DateTime<Local>,
    pub entry_type: String,
    pub source_or_destination: String,
    pub amount: f64,
    pub notes: String,
    pub linked_item_id: Option<Uuid>,
}

impl ItemRecord {
    pub fn new(
        date: DateTime<Local>,
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
    ) -> Self {
        Self {
            id: Uuid::new_v4(),
            date,
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
            overall_score: None,
        }
    }
}

impl MoneyRecord {
    pub fn new(
        date: DateTime<Local>,
        entry_type: String,
        source_or_destination: String,
        amount: f64,
        notes: String,
        linked_item_id: Option<Uuid>,
    ) -> Self {
        Self {
            id: Uuid::new_v4(),
            date,
            entry_type,
            source_or_destination,
            amount,
            notes,
            linked_item_id,
        }
    }
}
