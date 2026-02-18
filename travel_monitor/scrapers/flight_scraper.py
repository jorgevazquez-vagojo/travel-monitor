"""Google Flights Explore scraper using protobuf-encoded URLs.

Supports geo-spoofing: simulates searches from multiple countries
(ES, US, MX, CO, BR, UK, DE) to find the best price.
"""

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

# Geo-spoofing profiles: different locales/currencies to find best prices
GEO_PROFILES = [
    {
        "id": "ES", "locale": "es-ES", "currency": "EUR", "hl": "es",
        "timezone": "Europe/Madrid",
        "geolocation": {"latitude": 42.2328, "longitude": -8.7226},  # Vigo
    },
    {
        "id": "US", "locale": "en-US", "currency": "USD", "hl": "en",
        "timezone": "America/New_York",
        "geolocation": {"latitude": 40.7128, "longitude": -74.0060},  # NYC
    },
    {
        "id": "MX", "locale": "es-MX", "currency": "MXN", "hl": "es",
        "timezone": "America/Mexico_City",
        "geolocation": {"latitude": 19.4326, "longitude": -99.1332},  # CDMX
    },
    {
        "id": "CO", "locale": "es-CO", "currency": "COP", "hl": "es",
        "timezone": "America/Bogota",
        "geolocation": {"latitude": 4.7110, "longitude": -74.0721},  # Bogota
    },
    {
        "id": "UK", "locale": "en-GB", "currency": "GBP", "hl": "en",
        "timezone": "Europe/London",
        "geolocation": {"latitude": 51.5074, "longitude": -0.1278},  # London
    },
    {
        "id": "DE", "locale": "de-DE", "currency": "EUR", "hl": "de",
        "timezone": "Europe/Berlin",
        "geolocation": {"latitude": 52.5200, "longitude": 13.4050},  # Berlin
    },
]

# Approximate exchange rates to EUR (updated periodically)
EXCHANGE_TO_EUR = {
    "EUR": 1.0,
    "USD": 0.92,
    "GBP": 1.17,
    "MXN": 0.047,
    "COP": 0.00023,
    "BRL": 0.17,
}


def _to_eur(price, currency):
    """Convert a price to EUR using approximate exchange rates."""
    rate = EXCHANGE_TO_EUR.get(currency, 1.0)
    return round(price * rate, 2)


def _accept_cookies(page):
    """Handle Google cookie consent dialog."""
    for text in ["Aceptar todo", "Accept all", "Aceptar", "Alle akzeptieren"]:
        try:
            btn = page.locator(f"button:has-text('{text}')").first
            btn.click(timeout=3000)
            page.wait_for_timeout(1000)
            return
        except Exception:
            pass


def _extract_explore_data(page_text, destination_name, currency="EUR"):
    """Extract flight data from the Google Flights Explore page text."""
    dname_norm = normalize(destination_name)
    lines = page_text.split("\n")
    results = []

    # Currency symbols for different locales
    currency_patterns = {
        "EUR": r'([\d.]+)\s*€',
        "USD": r'\$\s*([\d,]+(?:\.\d{2})?)',
        "GBP": r'£\s*([\d,]+(?:\.\d{2})?)',
        "MXN": r'\$\s*([\d,]+(?:\.\d{2})?)',
        "COP": r'\$\s*([\d.,]+)',
        "BRL": r'R\$\s*([\d.,]+)',
    }
    price_pattern = currency_patterns.get(currency, r'([\d.]+)\s*€')

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

            # Try EUR first (always works), then locale-specific
            pm = re.search(r'([\d.]+)\s*€', next_line)
            if not pm:
                pm = re.search(price_pattern, next_line)
            if pm and price is None:
                raw = pm.group(1).replace(",", "").replace(".", "")
                # For EUR prices like "1.197 €", dots are thousands separators
                # For USD prices like "$1,197.00", need different parsing
                if currency == "EUR":
                    price = float(pm.group(1).replace(".", ""))
                else:
                    clean = pm.group(1).replace(",", "")
                    price = float(clean)
                continue

            if re.match(r'^\d+\s*(escala|stop|Stopp|parada)', next_line, re.IGNORECASE):
                stops = int(re.match(r'^(\d+)', next_line).group(1))
                continue
            if re.search(r'directo|nonstop|ohne Umstieg', next_line, re.IGNORECASE):
                stops = 0
                continue

            dm = re.match(r'^(\d{1,2})\s*h\s*(\d{1,2})?\s*m', next_line)
            if not dm:
                dm = re.match(r'^(\d{1,2})\s*Std\.\s*(\d{1,2})?\s*Min', next_line)
            if dm:
                h = int(dm.group(1))
                m = int(dm.group(2)) if dm.group(2) else 0
                duration_min = h * 60 + m
                duration_str = f"{h}h {m}m" if m else f"{h}h"
                continue

        if price and price > 10:
            # Convert to EUR
            price_eur = _to_eur(price, currency) if currency != "EUR" else price
            results.append({
                "price": price,
                "price_eur": price_eur,
                "currency": currency,
                "stops": stops,
                "duration_min": duration_min,
                "duration": duration_str,
                "airline": "",
            })
            break

    return results


def _scrape_single(page, route, cabin, dep_date, ret_date, geo=None):
    """Navigate to Explore URL for a given cabin/dates and extract data."""
    label = "Turista" if cabin == "economy" else "Business"
    currency = geo["currency"] if geo else "EUR"
    hl = geo["hl"] if geo else "es"

    # Build URL with geo-specific currency and language
    tfs = build_explore_tfs(
        route.origin_geo, route.destination_geo,
        dep_date, ret_date, cabin
    )
    url = f"https://www.google.com/travel/explore?tfs={tfs}&tfu=GgA&hl={hl}&curr={currency}"

    page.goto(url, timeout=30000, wait_until="networkidle")
    page.wait_for_timeout(5000)

    page_text = page.inner_text("body")
    flights = _extract_explore_data(page_text, route.destination_name, currency)

    if flights:
        return flights[0]
    return None


def _scrape_with_geo(route, cabin, dep_date, ret_date, browser) -> PriceResult:
    """Scrape a single week/cabin trying multiple geo locations for best price."""
    label = "Turista" if cabin == "economy" else "Business"
    print(f"    [{label}] {dep_date} -> {ret_date}")

    best_price_eur = None
    best_result = None
    best_geo = None

    for geo in GEO_PROFILES:
        try:
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale=geo["locale"],
                timezone_id=geo["timezone"],
                geolocation=geo["geolocation"],
                permissions=["geolocation"],
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            # Accept cookies
            page.goto(
                f"https://www.google.com/travel/flights?hl={geo['hl']}&curr={geo['currency']}",
                timeout=20000, wait_until="networkidle",
            )
            page.wait_for_timeout(1500)
            _accept_cookies(page)

            result = _scrape_single(page, route, cabin, dep_date, ret_date, geo)

            if result:
                price_eur = result.get("price_eur", result["price"])
                tag = f"{geo['id']}:{result['price']}{geo['currency']}"
                if price_eur <= 100:
                    # Likely bad parse, skip
                    pass
                elif best_price_eur is None or price_eur < best_price_eur:
                    best_price_eur = price_eur
                    best_result = result
                    best_geo = geo
                    tag += " *BEST*"
                print(f"      {tag}")

            page.close()
            ctx.close()
            page.wait_for_timeout(1000)

        except Exception as e:
            print(f"      {geo['id']}: error ({e})")
            try:
                ctx.close()
            except Exception:
                pass

    if best_result:
        print(f"      >> Mejor: {best_price_eur:.0f}EUR via {best_geo['id']}")
        return PriceResult(
            timestamp=datetime.now().isoformat(),
            route_id=route.id,
            transport_type="flight",
            cabin_class=cabin.upper(),
            price=best_price_eur,
            currency="EUR",
            airline=best_result.get("airline", ""),
            stops=best_result.get("stops", 0),
            duration=best_result.get("duration", ""),
            week_start=dep_date,
            travel_date=dep_date,
        )
    else:
        print(f"      Sin datos en ninguna ubicacion")
        return PriceResult(
            timestamp=datetime.now().isoformat(),
            route_id=route.id,
            transport_type="flight",
            cabin_class=cabin.upper(),
            week_start=dep_date,
            travel_date=dep_date,
        )


def scrape_flight_route(route: FlightRoute, geo_spoof=True) -> list:
    """Scrape a flight route for N weeks x cabins. Returns list of PriceResult.

    If geo_spoof=True, tries multiple country locations per week/cabin
    to find the lowest price. Each geo gets its own browser context.
    """
    print(f"\n  === Vuelos {route.id}: {route.origin_name} -> {route.destination_name} ===")
    if geo_spoof:
        print(f"  Geo-spoofing: {', '.join(g['id'] for g in GEO_PROFILES)}")
    results = []

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
            )

            # Generate week dates starting from next Monday
            today = datetime.now().date()
            days_until_monday = (7 - today.weekday()) % 7
            if days_until_monday == 0:
                days_until_monday = 7
            next_monday = today + timedelta(days=days_until_monday)

            for week_idx in range(route.weeks):
                dep_date = next_monday + timedelta(weeks=week_idx)
                ret_date = dep_date + timedelta(days=3)
                dep_str = dep_date.strftime("%Y-%m-%d")
                ret_str = ret_date.strftime("%Y-%m-%d")

                for cabin in route.classes:
                    if geo_spoof:
                        result = _scrape_with_geo(
                            route, cabin, dep_str, ret_str, browser
                        )
                    else:
                        # Simple mode: single geo (Spain)
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
                        page.goto(
                            "https://www.google.com/travel/flights?hl=es&curr=EUR",
                            timeout=30000, wait_until="networkidle",
                        )
                        page.wait_for_timeout(2000)
                        _accept_cookies(page)

                        data = _scrape_single(page, route, cabin, dep_str, ret_str)
                        if data:
                            result = PriceResult(
                                timestamp=datetime.now().isoformat(),
                                route_id=route.id,
                                transport_type="flight",
                                cabin_class=cabin.upper(),
                                price=data["price"],
                                currency="EUR",
                                airline=data.get("airline", ""),
                                stops=data.get("stops", 0),
                                duration=data.get("duration", ""),
                                week_start=dep_str,
                                travel_date=dep_str,
                            )
                        else:
                            result = PriceResult(
                                timestamp=datetime.now().isoformat(),
                                route_id=route.id,
                                transport_type="flight",
                                cabin_class=cabin.upper(),
                                week_start=dep_str,
                                travel_date=dep_str,
                            )
                        page.close()
                        ctx.close()

                    results.append(result)

            browser.close()

    except Exception as e:
        print(f"  Error scraping flights: {e}")
        import traceback
        traceback.print_exc()

    return results
