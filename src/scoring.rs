use crate::config::WeightsConfig;
use crate::models::ItemRecord;
use chrono::{Datelike, Local};

pub struct ScoreResult {
    pub field_scores: FieldScores,
    pub overall: f64,
}

pub struct FieldScores {
    pub date: f64,
    pub cost: f64,
    pub urgency: f64,
    pub value: f64,
    pub price_comp: f64,
    pub effect: f64,
}

pub fn score_item(item: &ItemRecord, cfg: &WeightsConfig) -> ScoreResult {
    let date_score = score_date(item, cfg);
    let cost_score = score_cost(item, cfg);
    let scores = FieldScores {
        date: date_score,
        cost: cost_score,
        urgency: item.urgency as f64,
        value: item.value as f64,
        price_comp: item.price_comp as f64,
        effect: item.effect as f64,
    };

    let pairs = vec![
        (scores.date, cfg.weights.date),
        (scores.cost, cfg.weights.cost),
        (scores.urgency, cfg.weights.urgency),
        (scores.value, cfg.weights.value),
        (scores.price_comp, cfg.weights.price_comp),
        (scores.effect, cfg.weights.effect),
    ];
    let overall = weighted_avg(&pairs);
    ScoreResult {
        field_scores: scores,
        overall,
    }
}

fn score_date(item: &ItemRecord, cfg: &WeightsConfig) -> f64 {
    if item.urgency == cfg.urgency_override {
        return 5.0;
    }
    let days_old = (Local::now().date_naive() - item.date.date_naive()).num_days();
    if days_old <= cfg.date_scoring.recent_days {
        1.0
    } else if days_old <= cfg.date_scoring.mid_days {
        3.0
    } else {
        5.0
    }
}

fn score_cost(item: &ItemRecord, cfg: &WeightsConfig) -> f64 {
    for band in &cfg.cost_bands {
        if let Some(max) = band.max {
            if item.cost <= max {
                return band.score;
            }
        } else {
            return band.score;
        }
    }
    1.0
}

fn weighted_avg(pairs: &[(f64, f64)]) -> f64 {
    let num: f64 = pairs.iter().map(|(s, w)| s * w).sum();
    let den: f64 = pairs.iter().map(|(_, w)| w).sum();
    if den == 0.0 { 0.0 } else { num / den }
}
