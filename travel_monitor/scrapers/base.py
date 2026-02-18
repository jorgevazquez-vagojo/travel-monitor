"""Base scraper interface and shared data classes."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class PriceResult:
    """A single price observation from any transport scraper."""
    timestamp: str
    route_id: str
    transport_type: str  # "flight" or "train"
    cabin_class: str     # "economy", "business", "turista", "preferente"
    price: Optional[float] = None
    currency: str = "EUR"
    # Flight-specific
    airline: str = ""
    stops: int = 0
    duration: str = ""
    # Train-specific
    train_type: str = ""
    departure_time: str = ""
    arrival_time: str = ""
    # Week tracking
    week_start: str = ""
    travel_date: str = ""

    @property
    def has_price(self):
        return self.price is not None and self.price > 0

    def to_csv_row(self):
        """Return dict for CSV writing."""
        return {
            "timestamp": self.timestamp,
            "route_id": self.route_id,
            "transport_type": self.transport_type,
            "cabin_class": self.cabin_class,
            "price": self.price if self.has_price else "",
            "currency": self.currency if self.has_price else "",
            "airline": self.airline,
            "stops": self.stops if self.transport_type == "flight" else "",
            "duration": self.duration,
            "train_type": self.train_type,
            "departure_time": self.departure_time,
            "arrival_time": self.arrival_time,
            "week_start": self.week_start,
            "travel_date": self.travel_date,
        }


CSV_HEADERS = [
    "timestamp", "route_id", "transport_type", "cabin_class",
    "price", "currency", "airline", "stops", "duration",
    "train_type", "departure_time", "arrival_time",
    "week_start", "travel_date",
]
