#!/usr/bin/env python3
"""
Redegal Travel Monitor — Multi-route flight & train price monitoring.

Monitors Google Flights (protobuf URLs) and Renfe trains.
12-week scanning, multi-route, interactive dashboard.

Usage:
    python monitor.py                     # All routes, single check
    python monitor.py --route VGO-MEX     # Single route
    python monitor.py --flights           # Only flights
    python monitor.py --trains            # Only trains
    python monitor.py --dashboard         # Regenerate dashboard
    python monitor.py --daemon            # Loop every N hours
"""

import sys
import time
import argparse
from datetime import datetime

from travel_monitor.config import load_config
from travel_monitor.storage import log_results, migrate_old_csv
from travel_monitor.alerts import (
    check_flight_alerts, check_train_alerts,
    build_summary_email, send_email,
)
from travel_monitor.dashboard import generate_dashboard
from travel_monitor.scrapers.flight_scraper import scrape_flight_route
from travel_monitor.scrapers.train_scraper import scrape_train_route


def run_check(config, route_filter=None, flights_only=False, trains_only=False):
    """Run a single check cycle for all configured routes."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"  {config.company} Travel Monitor")
    print(f"  {now}")
    print(f"  Routes: {len(config.flights)} flights, {len(config.trains)} trains")
    print(f"{'='*60}")

    flight_results = {}
    train_results = {}

    # --- Flights ---
    if not trains_only:
        for route in config.flights:
            if route_filter and route.id != route_filter:
                continue
            results = scrape_flight_route(route)
            flight_results[route.id] = results
            log_results(results)
            check_flight_alerts(results, route, config)

    # --- Trains ---
    if not flights_only:
        for route in config.trains:
            if route_filter and route.id != route_filter:
                continue
            results = scrape_train_route(route)
            train_results[route.id] = results
            log_results(results)
            check_train_alerts(results, route, config)

    # Dashboard
    generate_dashboard(config)

    # Summary email (only if we have data)
    if flight_results or train_results:
        summary = build_summary_email(config, flight_results, train_results)
        send_email(config,
            f"[{config.company}] Travel Monitor — {datetime.now().strftime('%d/%m %H:%M')}",
            summary)

    print(f"\n  Check complete at {datetime.now().strftime('%H:%M:%S')}")


def main():
    ap = argparse.ArgumentParser(description="Redegal Travel Monitor")
    ap.add_argument("--route", help="Single route ID (e.g. VGO-MEX, MAD-OUR)")
    ap.add_argument("--flights", action="store_true", help="Only flights")
    ap.add_argument("--trains", action="store_true", help="Only trains")
    ap.add_argument("--dashboard", action="store_true", help="Regenerate dashboard")
    ap.add_argument("--daemon", action="store_true", help="Continuous mode")
    ap.add_argument("--migrate", action="store_true", help="Migrate old prices.csv")
    args = ap.parse_args()

    config = load_config()

    if args.migrate:
        migrate_old_csv()
        return

    if args.dashboard:
        migrate_old_csv()
        generate_dashboard(config)
        return

    # Auto-migrate old CSV on first run
    migrate_old_csv()

    if args.daemon:
        hrs = config.check_interval_hours
        print(f"  Daemon: every {hrs}h (Ctrl+C to stop)\n")
        while True:
            try:
                run_check(config, args.route, args.flights, args.trains)
                print(f"\n  Next in {hrs}h...")
                time.sleep(hrs * 3600)
            except KeyboardInterrupt:
                print("\n  Stopped.")
                break
    else:
        run_check(config, args.route, args.flights, args.trains)


if __name__ == "__main__":
    main()
