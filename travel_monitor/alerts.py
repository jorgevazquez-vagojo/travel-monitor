"""Email alerts and macOS notifications for price drops."""

import re
import smtplib
import subprocess
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
    """Build a combined HTML email summary of all routes."""
    html = f"""
    <div style="font-family:sans-serif;max-width:700px;margin:0 auto;background:#1e293b;color:#e2e8f0;padding:24px;border-radius:12px">
    <h1 style="color:#60a5fa;text-align:center">{config.company} Travel Monitor</h1>
    <p style="text-align:center;color:#94a3b8">Resumen de precios</p>
    """

    if flight_results:
        html += '<h2 style="color:#3b82f6;border-bottom:1px solid #334155;padding-bottom:8px">Vuelos</h2>'
        for route_id, results in flight_results.items():
            priced = [r for r in results if r.has_price]
            if not priced:
                html += f'<p style="color:#94a3b8">{route_id}: Sin datos</p>'
                continue

            by_cabin = {}
            for r in priced:
                by_cabin.setdefault(r.cabin_class, []).append(r)

            html += f'<h3 style="color:#e2e8f0">{route_id}</h3>'
            html += '<table style="width:100%;border-collapse:collapse;margin:8px 0">'
            html += '<tr><th style="text-align:left;color:#94a3b8;padding:4px 8px">Clase</th>'
            html += '<th style="text-align:left;color:#94a3b8;padding:4px 8px">Mejor</th>'
            html += '<th style="text-align:left;color:#94a3b8;padding:4px 8px">Semana</th></tr>'

            for cabin, items in sorted(by_cabin.items()):
                best = min(items, key=lambda r: r.price)
                label = "Turista" if cabin == "ECONOMY" else "Business"
                html += f'<tr><td style="padding:4px 8px">{label}</td>'
                html += f'<td style="padding:4px 8px;font-weight:bold;color:#4ade80">{best.price:.0f}EUR</td>'
                html += f'<td style="padding:4px 8px">{best.week_start}</td></tr>'

            html += '</table>'

    if train_results:
        html += '<h2 style="color:#a855f7;border-bottom:1px solid #334155;padding-bottom:8px;margin-top:20px">Trenes</h2>'
        for route_id, results in train_results.items():
            priced = [r for r in results if r.has_price]
            if not priced:
                html += f'<p style="color:#94a3b8">{route_id}: Sin datos</p>'
                continue

            by_cabin = {}
            for r in priced:
                by_cabin.setdefault(r.cabin_class, []).append(r)

            html += f'<h3 style="color:#e2e8f0">{route_id}</h3>'
            html += '<table style="width:100%;border-collapse:collapse;margin:8px 0">'
            html += '<tr><th style="text-align:left;color:#94a3b8;padding:4px 8px">Clase</th>'
            html += '<th style="text-align:left;color:#94a3b8;padding:4px 8px">Mejor</th>'
            html += '<th style="text-align:left;color:#94a3b8;padding:4px 8px">Fecha</th></tr>'

            for cabin, items in sorted(by_cabin.items()):
                best = min(items, key=lambda r: r.price)
                label = "Turista" if cabin == "TURISTA" else "Preferente"
                html += f'<tr><td style="padding:4px 8px">{label}</td>'
                html += f'<td style="padding:4px 8px;font-weight:bold;color:#4ade80">{best.price:.0f}EUR</td>'
                html += f'<td style="padding:4px 8px">{best.travel_date}</td></tr>'

            html += '</table>'

    html += f"""
    <hr style="border-color:#334155;margin:20px 0">
    <p style="text-align:center;color:#64748b;font-size:12px">
    {config.company} Travel Monitor &mdash; Automatico cada {config.check_interval_hours}h
    </p></div>"""

    return html
