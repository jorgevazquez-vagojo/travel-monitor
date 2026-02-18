"""Email alerts and macOS notifications for price drops."""

import re
import smtplib
import subprocess
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from .config import Config, FlightRoute, TrainRoute
from .utils import build_google_url
from .scrapers.base import PriceResult


def notify_macos(title, msg):
    """Send macOS notification."""
    try:
        msg_safe = msg.replace('"', '\\"').replace("'", "\\'")
        title_safe = title.replace('"', '\\"')
        subprocess.run(["osascript", "-e",
            f'display notification "{msg_safe}" with title "{title_safe}" sound name "Glass"'
        ], check=True, capture_output=True)
    except Exception:
        pass


def send_email(config: Config, subject: str, body_html: str):
    """Send HTML email to all configured recipients."""
    email = config.email
    if not email.enabled:
        return
    if not email.smtp_user or not email.smtp_password:
        print("  [email] SMTP not configured")
        return
    if not email.recipients:
        print("  [email] No recipients configured")
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = email.from_addr
    msg["To"] = ", ".join(email.recipients)

    plain = re.sub(r'<[^>]+>', '', body_html).replace('&nbsp;', ' ')
    msg.attach(MIMEText(plain, "plain"))
    msg.attach(MIMEText(body_html, "html"))

    try:
        with smtplib.SMTP(email.smtp_host, email.smtp_port) as s:
            s.starttls()
            s.login(email.smtp_user, email.smtp_password)
            s.sendmail(email.from_addr, email.recipients, msg.as_string())
        print(f"  [email] Sent to {', '.join(email.recipients)}")
    except Exception as e:
        print(f"  [email] Error: {e}")


def check_flight_alerts(results: list, route: FlightRoute, config: Config):
    """Check flight price alerts and send notifications."""
    priced = [r for r in results if r.has_price]
    if not priced:
        return

    for cabin in route.classes:
        cabin_upper = cabin.upper()
        cabin_results = [r for r in priced if r.cabin_class == cabin_upper]
        if not cabin_results:
            continue

        best = min(cabin_results, key=lambda r: r.price)
        threshold_key = f"{cabin}_max"
        threshold = route.alerts.get(threshold_key, 9999)
        label = "Turista" if cabin == "economy" else "Business"

        if best.price <= threshold:
            title = f"COMPRAR! {label} {route.id} a {best.price:.0f}EUR"
            google_url = build_google_url(
                route.origin, route.destination,
                best.week_start, best.travel_date, cabin
            )

            notify_macos(f"{config.company} - {title}",
                         f"{best.airline or '?'} - {best.price:.0f}EUR - Compra ya!")

            send_email(config, f"[{config.company}] ALERTA: {title}",
                f"<h2 style='color:#16a34a'>{label} {route.id} a {best.price:.0f}EUR - COMPRAR</h2>"
                f"<p><b>Ruta:</b> {route.origin_name} &rarr; {route.destination_name}</p>"
                f"<p><b>Semana:</b> {best.week_start}</p>"
                f"<p><b>Escalas:</b> {best.stops}</p>"
                f"<p><b>Duracion:</b> {best.duration}</p>"
                f"<p><b>Umbral:</b> {threshold}EUR</p>"
                f"<hr>"
                f"<p style='font-size:20px'><a href='{google_url}'>"
                f"<b>COMPRAR EN GOOGLE FLIGHTS</b></a></p>"
                f"<p style='color:gray;font-size:12px'>— {config.company} Travel Monitor</p>"
            )
            print(f"  *** COMPRAR! {label} {route.id} a {best.price:.0f}EUR ***")
        else:
            diff = best.price - threshold
            print(f"  {label} {route.id}: {best.price:.0f}EUR — faltan {diff:.0f}EUR para umbral ({threshold}EUR)")


def check_train_alerts(results: list, route: TrainRoute, config: Config):
    """Check train price alerts and send notifications."""
    priced = [r for r in results if r.has_price]
    if not priced:
        return

    for cabin in route.classes:
        cabin_upper = cabin.upper()
        cabin_results = [r for r in priced if r.cabin_class == cabin_upper]
        if not cabin_results:
            continue

        best = min(cabin_results, key=lambda r: r.price)
        threshold_key = f"{cabin}_max"
        threshold = route.alerts.get(threshold_key, 9999)
        label = "Turista" if cabin == "turista" else "Preferente"

        if best.price <= threshold:
            title = f"COMPRAR! Tren {label} {route.id} a {best.price:.0f}EUR"

            notify_macos(f"{config.company} - {title}",
                         f"{best.train_type or '?'} - {best.price:.0f}EUR")

            send_email(config, f"[{config.company}] ALERTA: {title}",
                f"<h2 style='color:#16a34a'>Tren {label} {route.id} a {best.price:.0f}EUR</h2>"
                f"<p><b>Ruta:</b> {route.origin_name} &rarr; {route.destination_name}</p>"
                f"<p><b>Fecha:</b> {best.travel_date}</p>"
                f"<p><b>Tren:</b> {best.train_type}</p>"
                f"<p><b>Horario:</b> {best.departure_time} - {best.arrival_time}</p>"
                f"<p><b>Umbral:</b> {threshold}EUR</p>"
                f"<hr>"
                f"<p style='font-size:20px'><a href='https://www.renfe.com/es/es'>"
                f"<b>COMPRAR EN RENFE</b></a></p>"
                f"<p style='color:gray;font-size:12px'>— {config.company} Travel Monitor</p>"
            )
            print(f"  *** COMPRAR! Tren {label} {route.id} a {best.price:.0f}EUR ***")
        else:
            diff = best.price - threshold
            print(f"  Tren {label} {route.id}: {best.price:.0f}EUR — faltan {diff:.0f}EUR ({threshold}EUR)")


def build_summary_email(config: Config, flight_results: dict, train_results: dict) -> str:
    """Build a combined HTML email focused on Turista class prices.

    Shows the TOP 5 cheapest weeks for each route (Turista),
    plus a full grid of all weeks with color-coded prices.
    """
    now = datetime.now().strftime('%d/%m/%Y %H:%M')

    html = f"""
    <div style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:700px;margin:0 auto;background:#0f172a;color:#e2e8f0;border-radius:16px;overflow:hidden">
    <div style="background:linear-gradient(135deg,#1e40af,#7c3aed);padding:24px;text-align:center">
        <h1 style="color:#fff;margin:0;font-size:24px">{config.company} Travel Monitor</h1>
        <p style="color:#c7d2fe;margin:8px 0 0;font-size:14px">{now} &middot; Cada {config.check_interval_hours}h</p>
    </div>
    <div style="padding:20px">
    """

    # --- FLIGHTS: Focus on TURISTA ---
    if flight_results:
        for route_id, results in flight_results.items():
            priced = [r for r in results if r.has_price]
            if not priced:
                html += f'<p style="color:#94a3b8;padding:8px 0">{route_id}: Sin datos disponibles</p>'
                continue

            # Get route info
            route = None
            for fr in config.flights:
                if fr.id == route_id:
                    route = fr
                    break
            route_label = f"{route.origin_name} → {route.destination_name}" if route else route_id

            # Turista results
            turista = sorted(
                [r for r in priced if r.cabin_class == "ECONOMY"],
                key=lambda r: r.price
            )
            business = sorted(
                [r for r in priced if r.cabin_class == "BUSINESS"],
                key=lambda r: r.price
            )

            # Header with best turista price
            best_turista = turista[0] if turista else None
            best_biz = business[0] if business else None
            threshold = route.alerts.get("economy_max", 800) if route else 800

            html += f"""
            <div style="background:#1e293b;border-radius:12px;padding:16px;margin-bottom:16px;border:1px solid #334155">
            <h2 style="color:#60a5fa;margin:0 0 4px;font-size:18px">✈ {route_label}</h2>
            <p style="color:#64748b;margin:0 0 12px;font-size:12px">{route_id} &middot; 12 semanas &middot; Umbral {threshold}EUR</p>
            """

            # Best prices cards
            html += '<div style="display:flex;gap:12px;margin-bottom:16px">'

            if best_turista:
                is_buy = best_turista.price <= threshold
                color = "#4ade80" if is_buy else "#f87171"
                action = "COMPRAR" if is_buy else "Esperar"
                html += f"""
                <div style="flex:1;background:#0f172a;border-radius:10px;padding:14px;text-align:center;border:1px solid {'#4ade80' if is_buy else '#334155'}">
                    <div style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1px">Mejor Turista</div>
                    <div style="color:{color};font-size:32px;font-weight:800;margin:4px 0">{best_turista.price:.0f}€</div>
                    <div style="color:#94a3b8;font-size:12px">Semana {best_turista.week_start}</div>
                    <div style="color:#94a3b8;font-size:12px">{best_turista.stops} escala(s) &middot; {best_turista.duration}</div>
                    <div style="margin-top:8px"><span style="background:{'#16a34a' if is_buy else '#334155'};color:#fff;padding:4px 12px;border-radius:6px;font-size:12px;font-weight:700">{action}</span></div>
                </div>"""

            if best_biz:
                biz_threshold = route.alerts.get("business_max", 2200) if route else 2200
                is_buy_biz = best_biz.price <= biz_threshold
                html += f"""
                <div style="flex:1;background:#0f172a;border-radius:10px;padding:14px;text-align:center;border:1px solid #334155">
                    <div style="color:#94a3b8;font-size:11px;text-transform:uppercase;letter-spacing:1px">Mejor Business</div>
                    <div style="color:#c084fc;font-size:32px;font-weight:800;margin:4px 0">{best_biz.price:.0f}€</div>
                    <div style="color:#94a3b8;font-size:12px">Semana {best_biz.week_start}</div>
                </div>"""

            html += '</div>'

            # TOP 5 cheapest TURISTA weeks
            if turista:
                html += """
                <h3 style="color:#94a3b8;font-size:13px;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px">Top 5 Semanas Turista</h3>
                <table style="width:100%;border-collapse:collapse;margin-bottom:12px">
                <tr style="border-bottom:1px solid #334155">
                    <th style="text-align:left;color:#64748b;font-size:11px;padding:6px 8px">Semana</th>
                    <th style="text-align:right;color:#64748b;font-size:11px;padding:6px 8px">Precio</th>
                    <th style="text-align:center;color:#64748b;font-size:11px;padding:6px 8px">Escalas</th>
                    <th style="text-align:center;color:#64748b;font-size:11px;padding:6px 8px">Duracion</th>
                    <th style="text-align:center;color:#64748b;font-size:11px;padding:6px 8px">Estado</th>
                </tr>"""

                for r in turista[:5]:
                    is_buy = r.price <= threshold
                    color = "#4ade80" if is_buy else "#f87171"
                    badge_bg = "#064e3b" if is_buy else "#7f1d1d"
                    badge_text = "COMPRAR" if is_buy else "Esperar"
                    html += f"""
                    <tr style="border-bottom:1px solid #1e293b">
                        <td style="padding:8px;font-size:13px">{r.week_start}</td>
                        <td style="padding:8px;text-align:right;font-weight:700;color:{color};font-size:15px">{r.price:.0f}€</td>
                        <td style="padding:8px;text-align:center;color:#94a3b8;font-size:13px">{r.stops}</td>
                        <td style="padding:8px;text-align:center;color:#94a3b8;font-size:13px">{r.duration}</td>
                        <td style="padding:8px;text-align:center"><span style="background:{badge_bg};color:{color};padding:2px 8px;border-radius:6px;font-size:11px;font-weight:600">{badge_text}</span></td>
                    </tr>"""

                html += '</table>'

            # Full week grid (all turista)
            if turista:
                html += '<h3 style="color:#94a3b8;font-size:13px;margin:0 0 8px;text-transform:uppercase;letter-spacing:1px">Todas las semanas</h3>'
                html += '<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px">'

                prices = [r.price for r in turista]
                min_p, max_p = min(prices), max(prices)
                range_p = max_p - min_p if max_p > min_p else 1

                for r in sorted(turista, key=lambda x: x.week_start):
                    # Color gradient: green (cheap) -> yellow -> red (expensive)
                    ratio = (r.price - min_p) / range_p
                    if ratio < 0.33:
                        bg = "#064e3b"
                        fg = "#4ade80"
                    elif ratio < 0.66:
                        bg = "#78350f"
                        fg = "#fbbf24"
                    else:
                        bg = "#7f1d1d"
                        fg = "#f87171"

                    html += f'<div style="background:{bg};border-radius:8px;padding:6px 10px;text-align:center;min-width:70px">'
                    html += f'<div style="color:#94a3b8;font-size:10px">{r.week_start[5:]}</div>'
                    html += f'<div style="color:{fg};font-weight:700;font-size:14px">{r.price:.0f}€</div>'
                    html += '</div>'

                html += '</div>'

            # Links
            if route:
                gf_url = build_google_url(route.origin, route.destination, "", "", "economy")
                kayak_url = f"https://www.kayak.es/flights/{route.origin}-{route.destination}/?sort=price_a"
                html += f"""
                <div style="text-align:center;margin-top:12px">
                    <a href="{gf_url}" style="color:#60a5fa;font-size:13px;margin:0 8px">Google Flights</a>
                    <a href="{kayak_url}" style="color:#60a5fa;font-size:13px;margin:0 8px">Kayak</a>
                    <a href="https://www.skyscanner.es" style="color:#60a5fa;font-size:13px;margin:0 8px">Skyscanner</a>
                </div>"""

            html += '</div>'

    # --- TRAINS (only if we have actual price data) ---
    train_has_data = False
    if train_results:
        for route_id, results in train_results.items():
            if any(r.has_price for r in results):
                train_has_data = True
                break

    if train_has_data:
        html += '<h2 style="color:#a855f7;margin:16px 0 8px;font-size:16px">🚂 Trenes</h2>'
        for route_id, results in train_results.items():
            priced = [r for r in results if r.has_price]
            if not priced:
                continue

            turista = sorted(
                [r for r in priced if r.cabin_class == "TURISTA"],
                key=lambda r: r.price
            )
            if turista:
                best = turista[0]
                html += f"""
                <div style="background:#1e293b;border-radius:10px;padding:12px;margin-bottom:8px;border:1px solid #334155">
                    <div style="display:flex;justify-content:space-between;align-items:center">
                        <span style="color:#e2e8f0;font-size:14px">{route_id}</span>
                        <span style="color:#4ade80;font-weight:700;font-size:16px">{best.price:.0f}€</span>
                    </div>
                    <div style="color:#94a3b8;font-size:12px">Turista &middot; {best.travel_date} &middot; {best.train_type}</div>
                </div>"""

    html += f"""
    </div>
    <div style="background:#1e293b;padding:12px;text-align:center;border-top:1px solid #334155">
        <p style="color:#475569;font-size:11px;margin:0">{config.company} Travel Monitor &middot; Automatico cada {config.check_interval_hours}h</p>
    </div>
    </div>"""

    return html
