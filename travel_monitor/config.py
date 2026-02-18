"""Configuration loading and dataclasses for multi-route travel monitoring."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


SCRIPT_DIR = Path(__file__).parent.parent


@dataclass
class FlightRoute:
    id: str
    origin: str
    origin_name: str
    origin_geo: str
    destination: str
    destination_name: str
    destination_geo: str
    classes: list = field(default_factory=lambda: ["economy", "business"])
    alerts: dict = field(default_factory=lambda: {"economy_max": 800, "business_max": 2200})
    filters: dict = field(default_factory=lambda: {"max_stops": 1, "max_duration_hours": 16})
    weeks: int = 12
    adults: int = 1


@dataclass
class TrainRoute:
    id: str
    origin_name: str
    origin_code: str
    destination_name: str
    destination_code: str
    classes: list = field(default_factory=lambda: ["turista", "preferente"])
    alerts: dict = field(default_factory=lambda: {"turista_max": 30, "preferente_max": 60})
    weeks: int = 12


@dataclass
class EmailConfig:
    enabled: bool = True
    recipients: list = field(default_factory=list)
    from_addr: str = "monitor@redegal.com"
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""


@dataclass
class Config:
    company: str = "Redegal"
    currency: str = "EUR"
    check_interval_hours: int = 2
    email: EmailConfig = field(default_factory=EmailConfig)
    flights: list = field(default_factory=list)
    trains: list = field(default_factory=list)


def load_config(path: Optional[Path] = None) -> Config:
    """Load config from JSON file and return typed Config object."""
    config_path = path or (SCRIPT_DIR / "config.json")
    with open(config_path) as f:
        raw = json.load(f)

    email_raw = raw.get("email", {})
    # Support both old "to" (string) and new "recipients" (list)
    recipients = email_raw.get("recipients", [])
    if not recipients and email_raw.get("to"):
        recipients = [email_raw["to"]] if isinstance(email_raw["to"], str) else email_raw["to"]

    email = EmailConfig(
        enabled=email_raw.get("enabled", True),
        recipients=recipients,
        from_addr=email_raw.get("from", "monitor@redegal.com"),
        smtp_host=email_raw.get("smtp_host", "smtp.gmail.com"),
        smtp_port=email_raw.get("smtp_port", 587),
        smtp_user=email_raw.get("smtp_user", ""),
        smtp_password=email_raw.get("smtp_password", ""),
    )

    flights = []
    for fr in raw.get("flights", []):
        flights.append(FlightRoute(
            id=fr["id"],
            origin=fr["origin"],
            origin_name=fr["origin_name"],
            origin_geo=fr["origin_geo"],
            destination=fr["destination"],
            destination_name=fr["destination_name"],
            destination_geo=fr["destination_geo"],
            classes=fr.get("classes", ["economy", "business"]),
            alerts=fr.get("alerts", {"economy_max": 800, "business_max": 2200}),
            filters=fr.get("filters", {"max_stops": 1, "max_duration_hours": 16}),
            weeks=fr.get("weeks", 12),
            adults=fr.get("adults", 1),
        ))

    # Backward compat: if no flights[] but old flat config exists
    if not flights and raw.get("origin"):
        flights.append(FlightRoute(
            id=f"{raw['origin']}-{raw['destination']}",
            origin=raw["origin"],
            origin_name=raw.get("origin_name", raw["origin"]),
            origin_geo=raw.get("origin_geo", ""),
            destination=raw["destination"],
            destination_name=raw.get("destination_name", raw["destination"]),
            destination_geo=raw.get("destination_geo", ""),
            classes=["economy", "business"],
            alerts=raw.get("alerts", {"economy_max": 800, "business_max": 2200}),
            filters=raw.get("filters", {"max_stops": 1, "max_duration_hours": 16}),
            weeks=12,
            adults=raw.get("adults", 1),
        ))

    trains = []
    for tr in raw.get("trains", []):
        trains.append(TrainRoute(
            id=tr["id"],
            origin_name=tr["origin_name"],
            origin_code=tr["origin_code"],
            destination_name=tr["destination_name"],
            destination_code=tr["destination_code"],
            classes=tr.get("classes", ["turista", "preferente"]),
            alerts=tr.get("alerts", {"turista_max": 30, "preferente_max": 60}),
            weeks=tr.get("weeks", 12),
        ))

    return Config(
        company=raw.get("company", "Redegal"),
        currency=raw.get("currency", "EUR"),
        check_interval_hours=raw.get("check_interval_hours", 2),
        email=email,
        flights=flights,
        trains=trains,
    )
