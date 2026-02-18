"""CSV storage for flight and train price history."""

import csv
from pathlib import Path

from .scrapers.base import PriceResult, CSV_HEADERS

SCRIPT_DIR = Path(__file__).parent.parent
DATA_DIR = SCRIPT_DIR / "data"


def _ensure_data_dir():
    DATA_DIR.mkdir(exist_ok=True)


def get_csv_path(transport_type: str) -> Path:
    """Return CSV path for flights or trains."""
    _ensure_data_dir()
    return DATA_DIR / f"{transport_type}s.csv"


def log_results(results: list):
    """Append PriceResult list to the appropriate CSV file."""
    if not results:
        return

    by_type = {}
    for r in results:
        by_type.setdefault(r.transport_type, []).append(r)

    for transport_type, items in by_type.items():
        csv_path = get_csv_path(transport_type)
        new_file = not csv_path.exists()

        with open(csv_path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            if new_file:
                w.writeheader()
            for item in items:
                w.writerow(item.to_csv_row())


def read_history(transport_type: str, route_id: str = None) -> list:
    """Read CSV history, optionally filtered by route_id."""
    csv_path = get_csv_path(transport_type)
    if not csv_path.exists():
        return []

    rows = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            if route_id and r.get("route_id") != route_id:
                continue
            rows.append(r)
    return rows


def migrate_old_csv():
    """Migrate old prices.csv to new data/flights.csv format."""
    old_csv = SCRIPT_DIR / "prices.csv"
    if not old_csv.exists():
        return

    new_csv = get_csv_path("flight")
    if new_csv.exists():
        return  # Already migrated

    print("  Migrating old prices.csv -> data/flights.csv ...")
    rows = []
    with open(old_csv) as f:
        for r in csv.DictReader(f):
            rows.append({
                "timestamp": r.get("timestamp", ""),
                "route_id": "VGO-MEX",
                "transport_type": "flight",
                "cabin_class": r.get("cabin", "ECONOMY"),
                "price": r.get("price", ""),
                "currency": r.get("currency", ""),
                "airline": r.get("airline", ""),
                "stops": r.get("stops", ""),
                "duration": r.get("duration", ""),
                "train_type": "",
                "departure_time": "",
                "arrival_time": "",
                "week_start": "",
                "travel_date": "",
            })

    if rows:
        _ensure_data_dir()
        with open(new_csv, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            w.writeheader()
            w.writerows(rows)
        print(f"  Migrated {len(rows)} records.")
