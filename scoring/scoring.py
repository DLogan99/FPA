from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Tuple

from core.models import ItemRecord


@dataclass
class ScoreResult:
    field_scores: Dict[str, float]
    overall: float


def _score_date(item_date: datetime, config: Dict[str, int], urgency: int, urgency_override: int) -> float:
    if urgency == urgency_override:
        return 5.0
    recent_days = config.get("recent_days", 7)
    mid_days = config.get("mid_days", 30)
    days_old = (datetime.now() - item_date).days
    if days_old <= recent_days:
        return 1.0
    if days_old <= mid_days:
        return 3.0
    return 5.0


def _score_cost(cost: float, bands: List[Dict[str, float]]) -> float:
    for band in bands:
        max_val = band.get("max")
        if max_val is None:
            return float(band["score"])
        if cost <= float(max_val):
            return float(band["score"])
    return 1.0


def _weighted_average(pairs: List[Tuple[float, float]]) -> float:
    numerator = sum(score * weight for score, weight in pairs)
    denominator = sum(weight for _, weight in pairs) or 1.0
    return numerator / denominator


def score_item(item: ItemRecord, weights_config: Dict) -> ScoreResult:
    weights = weights_config.get("weights", {})
    date_cfg = weights_config.get("date_scoring", {})
    cost_bands = weights_config.get("cost_bands", [])
    urgency_override = weights_config.get("urgency_override", 5)

    scores = {
        "date": _score_date(item.date, date_cfg, item.urgency, urgency_override),
        "cost": _score_cost(item.cost, cost_bands),
        "urgency": float(item.urgency),
        "value": float(item.value),
        "price_comp": float(item.price_comp),
        "effect": float(item.effect),
    }

    pairs = [(scores[key], float(weights.get(key, 1.0))) for key in scores]
    overall = _weighted_average(pairs)
    scores["overall"] = overall
    return ScoreResult(field_scores=scores, overall=overall)
