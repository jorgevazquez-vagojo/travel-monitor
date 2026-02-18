"""Train price scraper with multiple provider fallbacks.

Strategy (in order):
1. Renfe — JS focus + keyboard (bypasses overlay menus)
2. Trainline — direct URL (no form interaction)
3. Omio — direct URL (no form interaction)

The Renfe website has overlay menus (rf-submenu__list) in the header that
intercept Playwright click events on the search form. The solution is to
use JavaScript focus() + keyboard typing instead of clicking inputs.
"""

import re
import sys
import time
import subprocess
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "playwright"])
    subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
    from playwright.sync_api import sync_playwright

from ..config import TrainRoute
from .base import PriceResult

# Station search terms for Renfe autocomplete
RENFE_STATION_NAMES = {
    "MADRI": "Madrid",
    "OUREN": "Ourense",
    "BARCE": "Barcelona",
    "MALAG": "Malaga",
}

# Trainline station URNs (fallback)
TRAINLINE_URNS = {
    "MADRI": "urn:trainline:generic:loc:5927",
    "OUREN": "urn:trainline:generic:loc:5976",
    "BARCE": "urn:trainline:generic:loc:5828",
    "MALAG": "urn:trainline:generic:loc:5958",
}

# Omio city slugs
OMIO_SLUGS = {
    "MADRI": "Madrid",
    "OUREN": "Ourense",
    "BARCE": "Barcelona",
    "MALAG": "Malaga",
}

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)


def _accept_cookies(page):
    """Handle cookie consent banners on various sites."""
    for selector in [
        "button#onetrust-accept-btn-handler",
        "button:has-text('Aceptar todas')",
        "button:has-text('Aceptar')",
        "button:has-text('Accept all')",
        "button:has-text('Accept')",
        "#cookies-accept",
    ]:
        try:
            btn = page.locator(selector).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                page.wait_for_timeout(500)
                return
        except Exception:
            pass


def _extract_renfe_results(text: str) -> list:
    """Parse Renfe results page text.

    Renfe results have this pattern per train:
        HH:MM h
        X horas Y minutos
        HH:MM h
        [Más rápido / Precio más bajo]
        Precio desde
        XX,XX €
    """
    results = []
    lines = text.split("\n")

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        # Look for departure time pattern: "07:14 h"
        dep_match = re.match(r'^(\d{1,2}:\d{2})\s*h$', line)
        if not dep_match:
            i += 1
            continue

        dep_time = dep_match.group(1)
        duration = ""
        arr_time = ""
        price = None
        has_connection = False

        # Scan next lines for duration, arrival, and price
        # Range is 14 to handle trains with connections (Enlace)
        for j in range(i + 1, min(i + 14, len(lines))):
            jline = lines[j].strip()

            # Skip "Enlace" marker
            if jline.lower() == "enlace":
                has_connection = True
                continue

            # Duration: "2 horas 22 minutos" or "X horas"
            dur_m = re.match(r'^(\d+)\s+horas?\s*(\d+)?\s*(minutos?)?$', jline)
            if dur_m:
                # Only take the first duration (trip), skip connection duration
                if not duration:
                    h = int(dur_m.group(1))
                    m = int(dur_m.group(2)) if dur_m.group(2) else 0
                    duration = f"{h}h {m}m" if m else f"{h}h"
                continue

            # Arrival time: "09:36 h"
            arr_m = re.match(r'^(\d{1,2}:\d{2})\s*h$', jline)
            if arr_m and not arr_time:
                arr_time = arr_m.group(1)
                continue

            # Price: "34,70 €"
            price_m = re.match(r'^(\d{1,3}(?:[.,]\d{2})?)\s*€$', jline)
            if price_m:
                raw = price_m.group(1).replace(",", ".")
                price = float(raw)
                break

        if price and 5 < price < 500:
            results.append({
                "price": price,
                "train_type": "",  # Not in text (rendered as images)
                "departure_time": dep_time,
                "arrival_time": arr_time,
                "duration": duration,
            })

        i += 1

    results.sort(key=lambda x: x["price"])
    return results


def _extract_generic_prices(text: str) -> list:
    """Generic price extraction for Trainline/Omio pages."""
    line_prices = []
    lines = text.split("\n")

    for i, line in enumerate(lines):
        stripped = line.strip()
        pm = re.search(r'(\d{1,3}(?:[.,]\d{2})?)\s*€', stripped)
        if not pm:
            continue
        raw = pm.group(1).replace(",", ".")
        price = float(raw)
        if price < 5 or price > 500:
            continue

        context = "\n".join(lines[max(0, i - 3):i + 4])

        train_type = ""
        for tt in ["AVE", "ALVIA", "AVLO", "Talgo", "Intercity", "Regional", "MD", "Avant"]:
            if tt.lower() in context.lower():
                train_type = tt
                break

        times = re.findall(r'(\d{1,2}:\d{2})', context)
        dep_time = times[0] if times else ""
        arr_time = times[1] if len(times) > 1 else ""

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
        raw_prices = set()
        for m in re.finditer(r'(\d{1,3}(?:[.,]\d{2})?)\s*€', text):
            raw = m.group(1).replace(",", ".")
            p = float(raw)
            if 5 < p < 500:
                raw_prices.add(p)
        for p in sorted(raw_prices)[:5]:
            line_prices.append({
                "price": p, "train_type": "", "departure_time": "",
                "arrival_time": "", "duration": "",
            })

    line_prices.sort(key=lambda x: x["price"])
    return line_prices


# ---------------------------------------------------------------------------
# Provider 1: Renfe (JS focus + keyboard — bypasses overlay)
# ---------------------------------------------------------------------------

def _scrape_renfe(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Scrape Renfe using JS focus + keyboard typing to bypass overlay menus."""
    origin_name = RENFE_STATION_NAMES.get(route.origin_code, route.origin_name)
    dest_name = RENFE_STATION_NAMES.get(route.destination_code, route.destination_name)

    try:
        dt = datetime.strptime(travel_date, "%Y-%m-%d")
        date_dd_mm = dt.strftime("%d/%m/%Y")
    except ValueError:
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                       "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent=_USER_AGENT,
            )
            page = ctx.new_page()

            page.goto("https://www.renfe.com/es/es", timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(4000)
            _accept_cookies(page)
            page.wait_for_timeout(500)

            # === ORIGIN (JS focus + keyboard — no click, no overlay issue) ===
            page.evaluate("document.getElementById('origin').focus()")
            page.wait_for_timeout(200)
            page.keyboard.type(origin_name, delay=50)
            page.wait_for_timeout(1500)
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(100)
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)

            # === DESTINATION (same approach) ===
            page.evaluate("document.getElementById('destination').focus()")
            page.wait_for_timeout(200)
            page.keyboard.type(dest_name, delay=50)
            page.wait_for_timeout(1500)
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(100)
            page.keyboard.press("Enter")
            page.wait_for_timeout(500)

            # === DATE (set hidden field directly via JS) ===
            page.evaluate(f"""() => {{
                document.querySelector('[name=FechaIdaSel]').value = '{date_dd_mm}';
                document.getElementById('first-input').value = '{date_dd_mm}';
            }}""")
            page.wait_for_timeout(200)

            # === Verify form state ===
            state = page.evaluate("""() => ({
                o: document.querySelector('[name=cdgoOrigen]').value,
                d: document.querySelector('[name=cdgoDestino]').value,
                f: document.querySelector('[name=FechaIdaSel]').value,
            })""")
            if not state["o"] or not state["d"]:
                print(f"        Renfe: form incomplete (o={state['o']}, d={state['d']})")
                browser.close()
                return None

            # === SEARCH (force click to bypass any remaining overlays) ===
            searched = False
            for sel in [
                "button:has-text('Buscar billete')",
                "button:has-text('Buscar')",
                "button[type='submit']",
            ]:
                try:
                    page.locator(sel).first.click(timeout=3000, force=True)
                    searched = True
                    break
                except Exception:
                    continue

            if not searched:
                # Last resort: submit form via JS
                page.evaluate("""() => {
                    const form = document.querySelector('form[action*="buscarTren"]');
                    if (form) form.submit();
                }""")

            # Wait for results page
            page.wait_for_timeout(10000)

            # Check we landed on results
            url = page.url
            if "venta.renfe.com" not in url:
                print(f"        Renfe: unexpected URL {url}")
                browser.close()
                return None

            body_text = page.inner_text("body")
            browser.close()

            # Parse Renfe-specific results format
            results = _extract_renfe_results(body_text)

            if not results:
                return None

            # For turista: return cheapest; for preferente: estimate ~1.6x turista
            if cabin == "turista":
                return results[0]
            else:
                # Preferente prices are not directly visible on results page
                # (would need to click a train). Estimate from turista.
                cheapest = results[0].copy()
                cheapest["price"] = round(cheapest["price"] * 1.6, 2)
                return cheapest

    except Exception as e:
        print(f"        Renfe error: {e}")

    return None


# ---------------------------------------------------------------------------
# Provider 2: Trainline (direct URL — no form interaction)
# ---------------------------------------------------------------------------

def _scrape_trainline(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Scrape Trainline search results via direct URL."""
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
        f"&selectedTab=train&lang=es"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                       "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent=_USER_AGENT,
            )
            page = ctx.new_page()

            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            _accept_cookies(page)
            page.wait_for_timeout(1000)

            # Scroll to trigger lazy-loaded results
            for _ in range(4):
                page.evaluate("window.scrollBy(0, 400)")
                page.wait_for_timeout(1500)

            page.wait_for_timeout(3000)
            body_text = page.inner_text("body")
            browser.close()

            results = _extract_generic_prices(body_text)
            if results:
                if cabin == "turista":
                    return results[0]
                else:
                    r = results[0].copy()
                    r["price"] = round(r["price"] * 1.6, 2)
                    return r

    except Exception as e:
        print(f"        Trainline error: {e}")

    return None


# ---------------------------------------------------------------------------
# Provider 3: Omio (direct URL — no form interaction)
# ---------------------------------------------------------------------------

def _scrape_omio(route: TrainRoute, travel_date: str, cabin: str) -> Optional[dict]:
    """Scrape Omio (formerly GoEuro) search results via direct URL."""
    origin = OMIO_SLUGS.get(route.origin_code, route.origin_name)
    dest = OMIO_SLUGS.get(route.destination_code, route.destination_name)

    url = (
        f"https://www.omio.es/search-frontend/results/"
        f"{quote(origin)}/{quote(dest)}/{travel_date}/1"
    )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=["--no-sandbox", "--disable-blink-features=AutomationControlled",
                       "--disable-dev-shm-usage"],
            )
            ctx = browser.new_context(
                viewport={"width": 1366, "height": 900},
                locale="es-ES",
                timezone_id="Europe/Madrid",
                user_agent=_USER_AGENT,
            )
            page = ctx.new_page()

            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            page.wait_for_timeout(5000)
            _accept_cookies(page)
            page.wait_for_timeout(1000)

            for _ in range(4):
                page.evaluate("window.scrollBy(0, 400)")
                page.wait_for_timeout(1500)

            page.wait_for_timeout(3000)
            body_text = page.inner_text("body")
            browser.close()

            results = _extract_generic_prices(body_text)
            if results:
                if cabin == "turista":
                    return results[0]
                else:
                    r = results[0].copy()
                    r["price"] = round(r["price"] * 1.6, 2)
                    return r

    except Exception as e:
        print(f"        Omio error: {e}")

    return None


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def scrape_train_route(route: TrainRoute) -> list:
    """Scrape a train route for N weeks x classes.

    Tries providers in order: Renfe -> Trainline -> Omio.
    Returns list of PriceResult.
    """
    print(f"\n  === Trenes {route.id}: {route.origin_name} -> {route.destination_name} ===")
    results = []

    today = datetime.now().date()
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

            data = None

            # 1. Renfe
            data = _scrape_renfe(route, date_str, cabin)

            # 2. Trainline fallback
            if not data or not data.get("price"):
                print(f"      Renfe sin datos, Trainline...")
                data = _scrape_trainline(route, date_str, cabin)

            # 3. Omio fallback
            if not data or not data.get("price"):
                print(f"      Trainline sin datos, Omio...")
                data = _scrape_omio(route, date_str, cabin)

            if data and data.get("price"):
                print(f"      {data['price']:.2f}EUR {data.get('departure_time', '')} {data.get('duration', '')}")
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

            time.sleep(2)

    return results
