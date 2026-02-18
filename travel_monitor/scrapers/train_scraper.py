"""Renfe train scraper using Playwright browser automation.

Navigates the actual Renfe website like a real user to extract
AVE/ALVIA prices for Madrid↔Ourense, Barcelona↔Ourense, Malaga↔Ourense.

Falls back to Trainline if Renfe fails.
"""

import re
import sys
import time
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

from ..config import TrainRoute
from .base import PriceResult

# Station names as they appear in Renfe search autocomplete
RENFE_STATION_NAMES = {
    "MADRI": "Madrid (Todas)",
    "OUREN": "Ourense",
    "BARCE": "Barcelona (Todas)",
    "MALAG": "Malaga",
}

# Trainline station URNs (fallback)
TRAINLINE_URNS = {
    "MADRI": "urn:trainline:generic:loc:5927",
    "OUREN": "urn:trainline:generic:loc:5976",
    "BARCE": "urn:trainline:generic:loc:5828",
    "MALAG": "urn:trainline:generic:loc:5958",
}


def _accept_cookies_renfe(page):
    """Handle Renfe cookie consent."""
    for selector in [
        "button#onetrust-accept-btn-handler",
        "button:has-text('Aceptar')",
        "button:has-text('Aceptar todas')",
        "button:has-text('Aceptar cookies')",
        "#cookies-accept",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=2000):
                btn.click(timeout=3000)
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def _extract_prices_from_text(text: str, cabin: str) -> list:
    """Extract train prices from page text.

    Returns list of dicts with price, train_type, times.
    """
    results = []

    # Find all price patterns (Spanish format: 45,50 € or 45.50€ or 45 €)
    price_matches = []
    for m in re.finditer(r'(\d{1,3}(?:[.,]\d{2})?)\s*€', text):
        raw = m.group(1).replace(",", ".")
        price = float(raw)
        if 5 < price < 500:
            price_matches.append((price, m.start()))

    if not price_matches:
        return []

    # Try to find associated train info near each price
    lines = text.split("\n")
    line_prices = []

    for i, line in enumerate(lines):
        stripped = line.strip()
        pm = re.search(r'(\d{1,3}(?:[.,]\d{2})?)\s*€', stripped)
        if not pm:
            continue
        raw = pm.group(1).replace(",", ".")
        price = float(raw)
        if price < 5 or price > 500:
            continue

        # Look around for train type and times
        context = "\n".join(lines[max(0, i-3):i+4])
        train_type = ""
        for tt in ["AVE", "ALVIA", "AVLO", "Talgo", "Intercity", "Regional", "MD", "Avant"]:
            if tt.lower() in context.lower():
                train_type = tt
                break

        # Extract times
        times = re.findall(r'(\d{1,2}:\d{2})', context)
        dep_time = times[0] if times else ""
        arr_time = times[1] if len(times) > 1 else ""

        # Duration
        dur_m = re.search(r'(\d{1,2})\s*h\s*(\d{1,2})?\s*m', context)
        duration = ""
        if dur_m:
            h = int(dur_m.group(1))
            m = int(dur_m.group(2)) if dur_m.group(2) else 0
            duration = f"{h}h {m}m" if m else f"{h}h"

        line_prices.append({
            "price": price,
            "train_type": train_type,
            "departure_time": dep_time,
            "arrival_time": arr_time,
            "duration": duration,
        })

    if not line_prices:
        # Fallback: just use raw prices
        prices = sorted(set(p for p, _ in price_matches))
        for p in prices[:5]:
            line_prices.append({
                "price": p,
                "train_type": "",
                "departure_time": "",
                "arrival_time": "",
                "duration": "",
            })

    # Sort by price
    line_prices.sort(key=lambda x: x["price"])

    # For turista, return cheapest; for preferente, return premium prices
    if cabin == "turista":
        return line_prices[:3]  # Top 3 cheapest
    else:
        # Preferente is typically in the upper price range
        if len(line_prices) > 3:
            return line_prices[len(line_prices)//2:][:3]
        return line_prices


def _scrape_renfe_playwright(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Scrape Renfe search results using Playwright."""
    origin_name = RENFE_STATION_NAMES.get(route.origin_code, route.origin_name)
    dest_name = RENFE_STATION_NAMES.get(route.destination_code, route.destination_name)

    try:
        dt = datetime.strptime(travel_date, "%Y-%m-%d")
        date_display = dt.strftime("%d/%m/%Y")
    except ValueError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            # Navigate to Renfe homepage
            page.goto("https://www.renfe.com/es/es", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(3000)
            _accept_cookies_renfe(page)
            page.wait_for_timeout(1000)

            # Fill origin
            try:
                origin_input = page.locator(
                    "#origin, input[placeholder*='Origen'], "
                    "input[aria-label*='Origen'], input[name*='origin']"
                ).first
                origin_input.click(timeout=5000)
                page.wait_for_timeout(500)
                origin_input.fill("")
                page.keyboard.type(origin_name.split(" (")[0], delay=80)
                page.wait_for_timeout(1500)

                # Select from autocomplete
                try:
                    page.locator("li:has-text('" + origin_name.split(" (")[0] + "')").first.click(timeout=3000)
                except Exception:
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                page.wait_for_timeout(500)
            except Exception as e:
                print(f"        Origin field error: {e}")
                browser.close()
                return None

            # Fill destination
            try:
                dest_input = page.locator(
                    "#destination, input[placeholder*='Destino'], "
                    "input[aria-label*='Destino'], input[name*='destin']"
                ).first
                dest_input.click(timeout=5000)
                page.wait_for_timeout(500)
                dest_input.fill("")
                page.keyboard.type(dest_name.split(" (")[0], delay=80)
                page.wait_for_timeout(1500)

                try:
                    page.locator("li:has-text('" + dest_name.split(" (")[0] + "')").first.click(timeout=3000)
                except Exception:
                    page.keyboard.press("ArrowDown")
                    page.keyboard.press("Enter")
                page.wait_for_timeout(500)
            except Exception as e:
                print(f"        Destination field error: {e}")
                browser.close()
                return None

            # Fill date
            try:
                date_input = page.locator(
                    "input[placeholder*='Ida'], input[aria-label*='ida'], "
                    "input[name*='fecha'], input[type='date']"
                ).first
                date_input.click(timeout=3000)
                page.wait_for_timeout(500)
                page.keyboard.press("Meta+a")
                page.keyboard.type(date_display, delay=50)
                page.keyboard.press("Enter")
                page.wait_for_timeout(500)
            except Exception:
                pass  # Some flows don't need manual date input

            # Click search
            try:
                for search_sel in [
                    "button:has-text('Buscar')",
                    "button[type='submit']",
                    "#searchButton",
                    "button:has-text('Buscar billete')",
                ]:
                    try:
                        page.locator(search_sel).first.click(timeout=3000)
                        break
                    except Exception:
                        continue
            except Exception:
                pass

            # Wait for results
            page.wait_for_timeout(8000)

            # Extract body text
            body_text = page.inner_text("body")

            # Try to find prices
            results = _extract_prices_from_text(body_text, cabin)

            browser.close()

            if results:
                return results[0]

    except Exception as e:
        print(f"        Renfe Playwright error: {e}")

    return None


def _scrape_trainline(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Fallback: scrape Trainline for Renfe prices."""
    origin_urn = TRAINLINE_URNS.get(route.origin_code)
    dest_urn = TRAINLINE_URNS.get(route.destination_code)

    if not origin_urn or not dest_urn:
        return None

    try:
        dt = datetime.strptime(travel_date, "%Y-%m-%d")
        outward = dt.strftime("%Y-%m-%dT06:00:00")
    except ValueError:
        return None

    url = (
        f"https://www.thetrainline.com/book/results?"
        f"origin={origin_urn}&destination={dest_urn}"
        f"&outwardDate={outward}&outwardDateType=departAfter"
        f"&journeySearchType=single&passengers%5B%5D=1996-01-01"
        f"&lang=es"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
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

            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(8000)

            # Accept cookies
            for btn_text in ["Accept", "Aceptar", "Accept all"]:
                try:
                    page.locator(f"button:has-text('{btn_text}')").first.click(timeout=2000)
                    page.wait_for_timeout(500)
                    break
                except Exception:
                    pass

            page.wait_for_timeout(3000)
            body_text = page.inner_text("body")

            results = _extract_prices_from_text(body_text, cabin)

            browser.close()

            if results:
                return results[0]

    except Exception as e:
        print(f"        Trainline error: {e}")

    return None


def scrape_train_route(route: TrainRoute) -> list:
    """Scrape a train route for N weeks x classes. Returns list of PriceResult.

    Tries Renfe first, falls back to Trainline if no data.
    """
    print(f"\n  === Trenes {route.id}: {route.origin_name} -> {route.destination_name} ===")
    results = []

    today = datetime.now().date()
    # Start from next Monday
    days_until_monday = (7 - today.weekday()) % 7
    if days_until_monday == 0:
        days_until_monday = 7
    next_monday = today + timedelta(days=days_until_monday)

    for week_idx in range(route.weeks):
        travel_date = next_monday + timedelta(weeks=week_idx)
        date_str = travel_date.strftime("%Y-%m-%d")

        for cabin in route.classes:
            label = "Turista" if cabin == "turista" else "Preferente"
            print(f"    [{label}] {date_str}")

            # Try Renfe first
            data = _scrape_renfe_playwright(route, date_str, cabin)

            # Fallback to Trainline
            if not data or not data.get("price"):
                print(f"      Renfe sin datos, probando Trainline...")
                data = _scrape_trainline(route, date_str, cabin)

            if data and data.get("price"):
                print(f"      {data['price']:.2f}EUR — {data.get('train_type', '?')}")
                results.append(PriceResult(
                    timestamp=datetime.now().isoformat(),
                    route_id=route.id,
                    transport_type="train",
                    cabin_class=cabin.upper(),
                    price=data["price"],
                    currency="EUR",
                    train_type=data.get("train_type", ""),
                    departure_time=data.get("departure_time", ""),
                    arrival_time=data.get("arrival_time", ""),
                    duration=data.get("duration", ""),
                    week_start=date_str,
                    travel_date=date_str,
                ))
            else:
                print(f"      Sin datos")
                results.append(PriceResult(
                    timestamp=datetime.now().isoformat(),
                    route_id=route.id,
                    transport_type="train",
                    cabin_class=cabin.upper(),
                    week_start=date_str,
                    travel_date=date_str,
                ))

            time.sleep(2)  # Rate limiting between requests

    return results
