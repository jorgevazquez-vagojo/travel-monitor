"""Google Flights Explore scraper using protobuf-encoded URLs."""

import re
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from ..utils import normalize, build_explore_url, build_explore_tfs
from ..config import FlightRoute
from .base import PriceResult

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Installing playwright...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

SCRIPT_DIR = Path(__file__).parent.parent.parent


def _accept_cookies(page):
    """Handle Google cookie consent dialog."""
    for text in ["Aceptar todo", "Accept all", "Aceptar"]:
        try:
            btn = page.locator(f"button:has-text('{text}')").first
            btn.click(timeout=3000)
            page.wait_for_timeout(1000)
            return
        except Exception:
            pass


def _extract_explore_data(page_text, destination_name):
    """Extract flight data from the Google Flights Explore page text."""
    dname_norm = normalize(destination_name)
    lines = page_text.split("\n")
    results = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        if dname_norm not in normalize(stripped):
            continue

        price = None
        stops = 0
        duration_min = 0
        duration_str = ""

        for j in range(1, 6):
            if i + j >= len(lines):
                break
            next_line = lines[i + j].strip()

            pm = re.search(r'([\d.]+)\s*€', next_line)
            if pm and price is None:
                price = float(pm.group(1).replace(".", ""))
                continue

            if re.match(r'^\d+\s*escala', next_line):
                stops = int(re.match(r'^(\d+)', next_line).group(1))
                continue
            if "directo" in next_line.lower():
                stops = 0
                continue

            dm = re.match(r'^(\d{1,2})\s*h\s*(\d{1,2})?\s*m', next_line)
            if dm:
                h = int(dm.group(1))
                m = int(dm.group(2)) if dm.group(2) else 0
                duration_min = h * 60 + m
                duration_str = f"{h}h {m}m" if m else f"{h}h"
                continue

        if price and price > 100:
            results.append({
                "price": price,
                "stops": stops,
                "duration_min": duration_min,
                "duration": duration_str,
                "airline": "",
            })
            break

    return results


def _scrape_single(page, route, cabin, dep_date, ret_date):
    """Navigate to Explore URL for a given cabin/dates and extract data."""
    label = "Turista" if cabin == "economy" else "Business"
    url = build_explore_url(
        route.origin_geo, route.destination_geo,
        dep_date, ret_date, cabin
    )
    print(f"    [{label}] {dep_date} -> {ret_date}")
    page.goto(url, timeout=30000, wait_until="networkidle")
    page.wait_for_timeout(5000)

    page_text = page.inner_text("body")
    flights = _extract_explore_data(page_text, route.destination_name)

    if flights:
        f = flights[0]
        print(f"      {f['price']}EUR, {f['stops']} escala(s), {f.get('duration', '?')}")
        return PriceResult(
            timestamp=datetime.now().isoformat(),
            route_id=route.id,
            transport_type="flight",
            cabin_class=cabin.upper(),
            price=f["price"],
            currency="EUR",
            airline=f.get("airline", ""),
            stops=f.get("stops", 0),
            duration=f.get("duration", ""),
            week_start=dep_date,
            travel_date=dep_date,
        )
    else:
        print(f"      Sin datos")
        return PriceResult(
            timestamp=datetime.now().isoformat(),
            route_id=route.id,
            transport_type="flight",
            cabin_class=cabin.upper(),
            week_start=dep_date,
            travel_date=dep_date,
        )


def scrape_flight_route(route: FlightRoute) -> list:
    """Scrape a flight route for N weeks × cabins. Returns list of PriceResult."""
    print(f"\n  === Vuelos {route.id}: {route.origin_name} -> {route.destination_name} ===")
    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="es-ES",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            # Accept cookies first
            page.goto(
                "https://www.google.com/travel/flights?hl=es&curr=EUR",
                timeout=30000, wait_until="networkidle",
            )
            page.wait_for_timeout(2000)
            _accept_cookies(page)

            # Generate week dates starting from next Monday
            today = datetime.now().date()
            # Find next Monday
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 7
            next_monday = today + timedelta(days=days_until_monday)

            for week_idx in range(route.weeks):
                dep_date = next_monday + timedelta(weeks=week_idx)
                # Return 3 days later (short trip)
                ret_date = dep_date + timedelta(days=3)
                dep_str = dep_date.strftime("%Y-%m-%d")
                ret_str = ret_date.strftime("%Y-%m-%d")

                for cabin in route.classes:
                    result = _scrape_single(page, route, cabin, dep_str, ret_str)
                    results.append(result)
                    page.wait_for_timeout(1500)  # Rate limiting

            # Screenshot of last page
            try:
                page.screenshot(
                    path=str(SCRIPT_DIR / "screenshot.png"), full_page=False
                )
            except Exception:
                pass

            browser.close()

    except Exception as e:
        print(f"  Error scraping flights: {e}")
        import traceback
        traceback.print_exc()

    return results
