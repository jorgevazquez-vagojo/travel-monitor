"""Renfe train scraper using httpx (DWR protocol) with Playwright fallback."""

import re
import json
import sys
import subprocess
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import httpx
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "httpx"])
    import httpx

from ..config import TrainRoute
from .base import PriceResult

# Renfe station codes for DWR
RENFE_STATIONS = {
    "MADRI": {"name": "Madrid", "code": "11000"},
    "OUREN": {"name": "Ourense", "code": "20200"},
    "BARCE": {"name": "Barcelona", "code": "71801"},
    "MALAG": {"name": "Malaga", "code": "12400"},
}


def _scrape_renfe_web(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Scrape Renfe prices via their public search page using httpx.

    Tries the Renfe availability endpoint which returns JSON.
    """
    origin = RENFE_STATIONS.get(route.origin_code, {})
    dest = RENFE_STATIONS.get(route.destination_code, {})

    if not origin or not dest:
        print(f"      Unknown station: {route.origin_code} or {route.destination_code}")
        return None

    # Format date for Renfe: DD/MM/YYYY
    try:
        dt = datetime.strptime(travel_date, "%Y-%m-%d")
        date_renfe = dt.strftime("%d/%m/%Y")
    except ValueError:
        return None

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "es-ES,es;q=0.9",
        "Referer": "https://www.renfe.com/es/es",
    }

    # Strategy 1: Try Renfe's horarios API
    try:
        search_url = "https://horarios.renfe.com/cer/hjcer310.jsp"
        params = {
            "nucleo": "10",
            "i": "s",
            "cp": "NO",
            "o": origin["code"],
            "d": dest["code"],
            "df": date_renfe,
            "ho": "00",
            "hd": "26",
            "TXTInfo": "",
        }
        client = httpx.Client(timeout=15, follow_redirects=True)
        resp = client.get(search_url, params=params, headers=headers)
        if resp.status_code == 200:
            text = resp.text
            # Parse basic schedule info if available
            trains = _parse_renfe_html(text, cabin)
            if trains:
                return trains[0]
    except Exception:
        pass

    # Strategy 2: Try Renfe venta endpoint
    try:
        venta_url = "https://venta.renfe.com/vol/buscarTren.do"
        form_data = {
            "tipoBusqueda": "autocomplete",
            "currenLocation": "menuBusqueda",
            "vengession": "s",
            "desession": "s",
            "cdgoOrigen": origin["code"],
            "cdgoDestino": dest["code"],
            "fecIdaVuworking": date_renfe,
            "workingyVuelta": "",
            "nAdultos": "1",
            "nNinos": "0",
            "nBebes": "0",
            "tipoTren": "AVE",
        }
        client = httpx.Client(timeout=15, follow_redirects=True)
        resp = client.post(venta_url, data=form_data, headers=headers)
        if resp.status_code == 200:
            trains = _parse_renfe_html(resp.text, cabin)
            if trains:
                return trains[0]
    except Exception:
        pass

    # Strategy 3: Playwright fallback
    return _scrape_renfe_playwright(route, travel_date, cabin)


def _parse_renfe_html(html: str, cabin: str) -> list:
    """Parse Renfe search results HTML for prices."""
    results = []

    # Look for price patterns in the HTML
    # Renfe shows prices like "45,50 €" or "45.50€"
    price_patterns = [
        r'(\d{1,3}[.,]\d{2})\s*€',
        r'precio["\s:>]*(\d{1,3}[.,]\d{2})',
        r'importe["\s:>]*(\d{1,3}[.,]\d{2})',
    ]

    prices = []
    for pattern in price_patterns:
        for m in re.finditer(pattern, html, re.IGNORECASE):
            p = float(m.group(1).replace(",", "."))
            if 5 < p < 500:
                prices.append(p)

    if not prices:
        return []

    # For turista, take the cheapest; for preferente, take a higher tier
    prices.sort()
    if cabin == "turista":
        price = prices[0]
    else:
        # Preferente is typically 1.5-2x turista
        price = prices[-1] if len(prices) > 1 else prices[0]

    # Try to extract train times
    time_pattern = r'(\d{1,2}[:.]\d{2})\s*[-–]\s*(\d{1,2}[:.]\d{2})'
    times = re.findall(time_pattern, html)

    results.append({
        "price": price,
        "train_type": "AVE/ALVIA",
        "departure_time": times[0][0] if times else "",
        "arrival_time": times[0][1] if times else "",
        "duration": "",
    })

    return results


def _scrape_renfe_playwright(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Fallback: use Playwright to scrape Renfe search page."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        from playwright.sync_api import sync_playwright

    origin = RENFE_STATIONS.get(route.origin_code, {})
    dest = RENFE_STATIONS.get(route.destination_code, {})
    if not origin or not dest:
        return None

    try:
        dt = datetime.strptime(travel_date, "%Y-%m-%d")
        date_renfe = dt.strftime("%d/%m/%Y")
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
                user_agent=(
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
            )
            page = ctx.new_page()

            # Navigate to Renfe search
            url = (
                f"https://www.renfe.com/es/es/viajar/informacion-util/horarios"
                f"?O={origin['code']}&D={dest['code']}&F={date_renfe}"
            )
            page.goto(url, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(5000)

            # Accept cookies
            for btn_text in ["Aceptar", "Aceptar todo", "Aceptar cookies"]:
                try:
                    page.locator(f"button:has-text('{btn_text}')").first.click(timeout=3000)
                    page.wait_for_timeout(1000)
                    break
                except Exception:
                    pass

            page.wait_for_timeout(3000)
            body_text = page.inner_text("body")

            # Extract prices from page text
            prices = []
            for m in re.finditer(r'(\d{1,3}[.,]\d{2})\s*€', body_text):
                price = float(m.group(1).replace(",", "."))
                if 5 < price < 500:
                    prices.append(price)

            # Extract times
            times = re.findall(r'(\d{1,2}:\d{2})', body_text)

            browser.close()

            if prices:
                prices.sort()
                price = prices[0] if cabin == "turista" else (prices[-1] if len(prices) > 1 else prices[0])
                return {
                    "price": price,
                    "train_type": "AVE/ALVIA",
                    "departure_time": times[0] if times else "",
                    "arrival_time": times[1] if len(times) > 1 else "",
                    "duration": "",
                }

    except Exception as e:
        print(f"      Playwright fallback error: {e}")

    return None


def scrape_train_route(route: TrainRoute) -> list:
    """Scrape a train route for N weeks × classes. Returns list of PriceResult."""
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

            data = _scrape_renfe_web(route, date_str, cabin)

            if data and data.get("price"):
                print(f"      {data['price']}EUR — {data.get('train_type', '?')}")
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

    return results
