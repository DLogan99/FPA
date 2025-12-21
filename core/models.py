from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional


DATE_FMT = "%Y-%m-%d %H:%M"


@dataclass
class ItemRecord:
    id: str
    date: datetime
    product: str
    description: str
    location: str
    reference: str
    cost: float
    urgency: int
    value: int
    price_comp: int
    effect: int
    justification: str
    recurrence: str = ""
    overall_score: Optional[float] = None

    @classmethod
    def headers(cls) -> list[str]:
        return [
            "id",
            "date",
            "product",
            "description",
            "location",
            "reference",
            "cost",
            "urgency",
            "value",
            "price_comp",
            "effect",
            "justification",
            "recurrence",
            "overall_score",
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str], date_format: str = DATE_FMT) -> "ItemRecord":
        return cls(
            id=row["id"],
            date=datetime.strptime(row["date"], date_format),
            product=row.get("product", ""),
            description=row.get("description", ""),
            location=row.get("location", ""),
            reference=row.get("reference", ""),
            cost=float(row.get("cost", "0") or 0),
            urgency=int(row.get("urgency", "1") or 1),
            value=int(row.get("value", "1") or 1),
            price_comp=int(row.get("price_comp", "1") or 1),
            effect=int(row.get("effect", "1") or 1),
            justification=row.get("justification", ""),
            recurrence=row.get("recurrence", ""),
            overall_score=float(row["overall_score"]) if row.get("overall_score") else None,
        )

    def to_row(self, date_format: str = DATE_FMT) -> Dict[str, str]:
        return {
            "id": self.id,
            "date": self.date.strftime(date_format),
            "product": self.product,
            "description": self.description,
            "location": self.location,
            "reference": self.reference,
            "cost": f"{self.cost:.2f}",
            "urgency": str(self.urgency),
            "value": str(self.value),
            "price_comp": str(self.price_comp),
            "effect": str(self.effect),
            "justification": self.justification,
            "recurrence": self.recurrence,
            "overall_score": f"{self.overall_score:.2f}" if self.overall_score is not None else "",
        }


@dataclass
class MoneyRecord:
    id: str
    date: datetime
    entry_type: str
    source_or_destination: str
    amount: float
    notes: str = ""
    linked_item_id: str = ""

    @classmethod
    def headers(cls) -> list[str]:
        return [
            "id",
            "date",
            "entry_type",
            "source_or_destination",
            "amount",
            "notes",
            "linked_item_id",
        ]

    @classmethod
    def from_row(cls, row: Dict[str, str], date_format: str = DATE_FMT) -> "MoneyRecord":
        return cls(
            id=row["id"],
            date=datetime.strptime(row["date"], date_format),
            entry_type=row.get("entry_type", "income"),
            source_or_destination=row.get("source_or_destination", ""),
            amount=float(row.get("amount", "0") or 0),
            notes=row.get("notes", ""),
            linked_item_id=row.get("linked_item_id", ""),
        )

    def to_row(self, date_format: str = DATE_FMT) -> Dict[str, str]:
        return {
            "id": self.id,
            "date": self.date.strftime(date_format),
            "entry_type": self.entry_type,
            "source_or_destination": self.source_or_destination,
            "amount": f"{self.amount:.2f}",
            "notes": self.notes,
            "linked_item_id": self.linked_item_id,
        }
