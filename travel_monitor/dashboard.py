"""Interactive HTML dashboard generator with tabs for Flights/Trains."""

import json
from datetime import datetime
from pathlib import Path

from .config import Config
from .storage import read_history
from .utils import build_google_url

SCRIPT_DIR = Path(__file__).parent.parent
DASHBOARD_FILE = SCRIPT_DIR / "dashboard.html"
OUTPUT_DIR = SCRIPT_DIR / "output"


def generate_dashboard(config: Config):
    """Generate interactive HTML dashboard with Flights/Trains tabs."""

    # Gather all flight data
    flight_data = {}
    for route in config.flights:
        rows = read_history("flight", route.id)
        flight_data[route.id] = {
            "route": route,
            "rows": rows,
        }

    # Gather all train data
    train_data = {}
    for route in config.trains:
        rows = read_history("train", route.id)
        train_data[route.id] = {
            "route": route,
            "rows": rows,
        }

    # Build JSON data for injection
    flight_json = {}
    for rid, d in flight_data.items():
        route = d["route"]
        rows = d["rows"]
        by_cabin = {}
        for cabin in ["ECONOMY", "BUSINESS"]:
            cabin_rows = [r for r in rows if r.get("cabin_class") == cabin]
            by_cabin[cabin] = {
                "timestamps": [r["timestamp"][:16].replace("T", " ") for r in cabin_rows],
                "prices": [float(r["price"]) if r.get("price") else None for r in cabin_rows],
                "weeks": [r.get("week_start", "") for r in cabin_rows],
            }

        # Best prices per week
        week_best = {}
        for r in rows:
            if not r.get("price"):
                continue
            ws = r.get("week_start", "")
            cabin = r.get("cabin_class", "")
            key = f"{ws}_{cabin}"
            price = float(r["price"])
            if key not in week_best or price < week_best[key]["price"]:
                week_best[key] = {"price": price, "week": ws, "cabin": cabin}

        flight_json[rid] = {
            "label": f"{route.origin_name} → {route.destination_name}",
            "origin": route.origin,
            "destination": route.destination,
            "by_cabin": by_cabin,
            "week_best": list(week_best.values()),
            "alerts": route.alerts,
            "google_url": build_google_url(route.origin, route.destination, "", "", "economy"),
        }

    train_json = {}
    for rid, d in train_data.items():
        route = d["route"]
        rows = d["rows"]
        by_cabin = {}
        for cabin in ["TURISTA", "PREFERENTE"]:
            cabin_rows = [r for r in rows if r.get("cabin_class") == cabin]
            by_cabin[cabin] = {
                "timestamps": [r["timestamp"][:16].replace("T", " ") for r in cabin_rows],
                "prices": [float(r["price"]) if r.get("price") else None for r in cabin_rows],
                "dates": [r.get("travel_date", "") for r in cabin_rows],
            }

        week_best = {}
        for r in rows:
            if not r.get("price"):
                continue
            td = r.get("travel_date", "")
            cabin = r.get("cabin_class", "")
            key = f"{td}_{cabin}"
            price = float(r["price"])
            if key not in week_best or price < week_best[key]["price"]:
                week_best[key] = {"price": price, "date": td, "cabin": cabin}

        train_json[rid] = {
            "label": f"{route.origin_name} → {route.destination_name}",
            "by_cabin": by_cabin,
            "week_best": list(week_best.values()),
            "alerts": route.alerts,
        }

    flight_routes_json = json.dumps(flight_json, ensure_ascii=False)
    train_routes_json = json.dumps(train_json, ensure_ascii=False)
    flight_ids = json.dumps(list(flight_json.keys()))
    train_ids = json.dumps(list(train_json.keys()))
    company = config.company
    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    interval = config.check_interval_hours

    html = f"""<!DOCTYPE html>
<html lang="es"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{company} — Travel Monitor</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;background:#0f172a;color:#e2e8f0;padding:16px}}
.w{{max-width:1200px;margin:0 auto}}
.hd{{text-align:center;margin-bottom:20px}}
h1{{font-size:1.8em;background:linear-gradient(135deg,#3b82f6,#a855f7);-webkit-background-clip:text;-webkit-text-fill-color:transparent;display:inline}}
.co{{font-size:.8em;color:#64748b;background:#1e293b;padding:2px 8px;border-radius:6px;margin-left:8px}}
.sub{{color:#94a3b8;font-size:.9em;margin-top:4px}}

/* Tabs */
.tabs{{display:flex;gap:4px;margin-bottom:16px;border-bottom:2px solid #334155;padding-bottom:0}}
.tab{{padding:10px 24px;cursor:pointer;border-radius:8px 8px 0 0;font-weight:600;font-size:.9em;transition:all .2s;border:1px solid transparent;border-bottom:none}}
.tab:hover{{background:#1e293b}}
.tab.active{{background:#1e293b;color:#60a5fa;border-color:#334155}}
.tab-flight.active{{color:#3b82f6}}
.tab-train.active{{color:#a855f7}}
.tab-content{{display:none}}.tab-content.active{{display:block}}

/* Route selector */
.route-sel{{margin-bottom:16px;display:flex;align-items:center;gap:12px;flex-wrap:wrap}}
.route-sel label{{color:#94a3b8;font-size:.85em}}
.route-sel select{{background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:8px;padding:8px 16px;font-size:.9em;cursor:pointer}}
.route-sel select:focus{{outline:none;border-color:#3b82f6}}

/* Cards */
.best{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin:16px 0}}
.best-card{{background:#1e293b;border-radius:14px;padding:20px;border:1px solid #334155;text-align:center}}
.best-card.hit{{border-color:#4ade80;box-shadow:0 0 20px rgba(74,222,128,.15)}}
.best-label{{font-size:.8em;color:#94a3b8;margin-bottom:4px}}
.best-price{{font-size:2.2em;font-weight:800}}.best-price.g{{color:#4ade80}}.best-price.r{{color:#f87171}}.best-price.p{{color:#c084fc}}
.best-info{{font-size:.82em;color:#94a3b8;margin-top:6px}}
.best-action{{margin-top:10px}}
.best-action a{{display:inline-block;padding:8px 20px;border-radius:8px;font-weight:700;font-size:.85em;text-decoration:none}}
.btn-buy{{background:#16a34a;color:#fff}}.btn-wait{{background:#334155;color:#94a3b8}}

/* Charts */
.chs{{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-bottom:16px}}
@media(max-width:700px){{.chs,.best{{grid-template-columns:1fr}}}}
.ch{{background:#1e293b;border-radius:12px;padding:14px;border:1px solid #334155}}
.ch h3{{font-size:.85em;color:#94a3b8;margin-bottom:8px}}

/* Week grid */
.week-grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(80px,1fr));gap:6px;margin:16px 0}}
.week-cell{{background:#1e293b;border-radius:8px;padding:8px 6px;text-align:center;border:1px solid #334155;font-size:.78em}}
.week-cell .wk{{color:#64748b;font-size:.72em}}.week-cell .wp{{font-weight:700;font-size:1.1em}}
.week-cell.cheap{{border-color:#4ade80;background:#064e3b}}.week-cell.mid{{border-color:#fbbf24;background:#78350f}}.week-cell.exp{{border-color:#f87171;background:#7f1d1d}}

/* Links */
.links{{text-align:center;margin:14px 0}}.links a{{color:#60a5fa;margin:0 10px;font-size:.85em}}

/* Table */
table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden;border:1px solid #334155;margin-bottom:14px}}
th{{background:#334155;padding:8px 10px;text-align:left;font-size:.75em;color:#94a3b8}}
td{{padding:7px 10px;border-bottom:1px solid #293548;font-size:.82em}}
tr:hover td{{background:#263548}}
.bg{{display:inline-block;padding:2px 7px;border-radius:8px;font-size:.72em;font-weight:600}}
.bg-g{{background:#064e3b;color:#4ade80}}.bg-r{{background:#7f1d1d;color:#f87171}}.bg-y{{background:#78350f;color:#fbbf24}}.bg-p{{background:#3b0764;color:#c084fc}}
.ft{{text-align:center;color:#475569;font-size:.72em;margin-top:14px}}
</style></head><body>
<div class="w">
<div class="hd"><h1>Travel Monitor</h1><span class="co">{company}</span>
<p class="sub">Vuelos + Trenes &middot; Multiruta &middot; Cada {interval}h</p></div>

<div class="tabs">
<div class="tab tab-flight active" onclick="switchTab('flights')">Vuelos</div>
<div class="tab tab-train" onclick="switchTab('trains')">Trenes</div>
</div>

<!-- FLIGHTS TAB -->
<div id="tab-flights" class="tab-content active">
<div class="route-sel">
<label>Ruta:</label>
<select id="flight-route-select" onchange="renderFlightRoute(this.value)"></select>
</div>
<div id="flight-best" class="best"></div>
<div class="links" id="flight-links"></div>
<div id="flight-charts" class="chs">
<div class="ch"><h3 id="fc1-title">Turista</h3><canvas id="fc1"></canvas></div>
<div class="ch"><h3 id="fc2-title">Business</h3><canvas id="fc2"></canvas></div>
</div>
<h3 style="color:#94a3b8;font-size:.85em;margin-bottom:8px">Precios por semana (Turista)</h3>
<div id="flight-week-grid" class="week-grid"></div>
<h3 style="color:#94a3b8;font-size:.85em;margin:12px 0 8px">Historial</h3>
<table><thead><tr><th>Fecha</th><th>Semana</th><th>Clase</th><th>Precio</th><th>Escalas</th><th>Duracion</th></tr></thead>
<tbody id="flight-tbody"></tbody></table>
</div>

<!-- TRAINS TAB -->
<div id="tab-trains" class="tab-content">
<div class="route-sel">
<label>Ruta:</label>
<select id="train-route-select" onchange="renderTrainRoute(this.value)"></select>
</div>
<div id="train-best" class="best"></div>
<div class="links" id="train-links"><a href="https://www.renfe.com/es/es" target="_blank">Renfe</a></div>
<div id="train-charts" class="chs">
<div class="ch"><h3 id="tc1-title">Turista</h3><canvas id="tc1"></canvas></div>
<div class="ch"><h3 id="tc2-title">Preferente</h3><canvas id="tc2"></canvas></div>
</div>
<h3 style="color:#94a3b8;font-size:.85em;margin-bottom:8px">Precios por fecha (Turista)</h3>
<div id="train-week-grid" class="week-grid"></div>
<h3 style="color:#94a3b8;font-size:.85em;margin:12px 0 8px">Historial</h3>
<table><thead><tr><th>Fecha</th><th>Viaje</th><th>Clase</th><th>Precio</th><th>Tren</th><th>Horario</th></tr></thead>
<tbody id="train-tbody"></tbody></table>
</div>

<p class="ft">{company} Travel Monitor &middot; {now_str} &middot; Cada {interval}h</p>
</div>
<script>
const FD={flight_routes_json};
const TD={train_routes_json};
const FIDS={flight_ids};
const TIDS={train_ids};

let fCharts=[null,null],tCharts=[null,null];

function switchTab(tab){{
  document.querySelectorAll('.tab-content').forEach(e=>e.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(e=>e.classList.remove('active'));
  document.getElementById('tab-'+tab).classList.add('active');
  document.querySelector('.tab-'+(tab==='flights'?'flight':'train')).classList.add('active');
}}

// --- Flights ---
function populateFlightSelect(){{
  const sel=document.getElementById('flight-route-select');
  sel.innerHTML='';
  FIDS.forEach(id=>{{
    const opt=document.createElement('option');
    opt.value=id;opt.textContent=id+' — '+FD[id].label;
    sel.appendChild(opt);
  }});
  if(FIDS.length)renderFlightRoute(FIDS[0]);
}}

function renderFlightRoute(rid){{
  const d=FD[rid];if(!d)return;
  const eco=d.by_cabin.ECONOMY||{{timestamps:[],prices:[]}};
  const biz=d.by_cabin.BUSINESS||{{timestamps:[],prices:[]}};
  const et=d.alerts.economy_max||800,bt=d.alerts.business_max||2200;

  // Best cards
  const ev=eco.prices.filter(p=>p!==null),bv=biz.prices.filter(p=>p!==null);
  const ebest=ev.length?Math.min(...ev):null,bbest=bv.length?Math.min(...bv):null;
  const eHit=ebest!==null&&ebest<=et,bHit=bbest!==null&&bbest<=bt;
  document.getElementById('flight-best').innerHTML=`
  <div class="best-card ${{eHit?'hit':''}}">
    <div class="best-label">Mejor Turista</div>
    <div class="best-price ${{eHit?'g':'r'}}">${{ebest!==null?ebest.toFixed(0)+'\\u20ac':'\\u2014'}}</div>
    <div class="best-info">Umbral: ${{et}}\\u20ac</div>
    <div class="best-action"><a class="${{eHit?'btn-buy':'btn-wait'}}" href="${{d.google_url||'#'}}" target="_blank">${{eHit?'COMPRAR':'Esperar'}}</a></div>
  </div>
  <div class="best-card ${{bHit?'hit':''}}">
    <div class="best-label">Mejor Business</div>
    <div class="best-price ${{bHit?'g':'p'}}">${{bbest!==null?bbest.toFixed(0)+'\\u20ac':'\\u2014'}}</div>
    <div class="best-info">Umbral: ${{bt}}\\u20ac</div>
    <div class="best-action"><a class="${{bHit?'btn-buy':'btn-wait'}}" href="${{d.google_url||'#'}}" target="_blank">${{bHit?'COMPRAR':'Esperar'}}</a></div>
  </div>`;

  // Links
  document.getElementById('flight-links').innerHTML=`
  <a href="${{d.google_url||'#'}}" target="_blank">Google Flights</a>
  <a href="https://www.kayak.es/flights/${{d.origin}}-${{d.destination}}/?sort=price_a" target="_blank">Kayak</a>
  <a href="https://www.skyscanner.es" target="_blank">Skyscanner</a>`;

  // Charts
  document.getElementById('fc1-title').textContent='Turista — Umbral '+et+'\\u20ac';
  document.getElementById('fc2-title').textContent='Business — Umbral '+bt+'\\u20ac';
  if(fCharts[0])fCharts[0].destroy();if(fCharts[1])fCharts[1].destroy();
  fCharts[0]=mkChart('fc1',eco.timestamps,eco.prices,et,'#3b82f6');
  fCharts[1]=mkChart('fc2',biz.timestamps,biz.prices,bt,'#a855f7');

  // Week grid (economy best per week)
  const weekBest={{}};
  (d.week_best||[]).filter(w=>w.cabin==='ECONOMY').forEach(w=>{{
    if(!weekBest[w.week]||w.price<weekBest[w.week])weekBest[w.week]=w.price;
  }});
  const weeks=Object.keys(weekBest).sort();
  const wPrices=weeks.map(w=>weekBest[w]);
  const wMin=wPrices.length?Math.min(...wPrices):0;
  const wMax=wPrices.length?Math.max(...wPrices):0;
  const wMid=wMin+(wMax-wMin)/3;const wHi=wMin+2*(wMax-wMin)/3;
  let wgHtml='';
  weeks.forEach(w=>{{
    const p=weekBest[w];
    const cls=p<=wMid?'cheap':p<=wHi?'mid':'exp';
    wgHtml+=`<div class="week-cell ${{cls}}"><div class="wk">${{w}}</div><div class="wp">${{p.toFixed(0)}}\\u20ac</div></div>`;
  }});
  document.getElementById('flight-week-grid').innerHTML=wgHtml||'<p style="color:#64748b">Sin datos de semanas</p>';

  // History table
  const allRows=[...eco.timestamps.map((t,i)=>({{ts:t,cabin:'Turista',price:eco.prices[i],week:eco.weeks?eco.weeks[i]:'',th:et}})),
                  ...biz.timestamps.map((t,i)=>({{ts:t,cabin:'Business',price:biz.prices[i],week:biz.weeks?biz.weeks[i]:'',th:bt}}))];
  allRows.sort((a,b)=>b.ts.localeCompare(a.ts));
  const tb=document.getElementById('flight-tbody');tb.innerHTML='';
  allRows.slice(0,100).forEach(r=>{{
    const ok=r.price!==null&&r.price<=r.th;
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${{r.ts}}</td><td>${{r.week}}</td>
    <td><span class="bg ${{r.cabin==='Business'?'bg-y':'bg-g'}}">${{r.cabin}}</span></td>
    <td style="font-weight:700;color:${{ok?'#4ade80':'#f87171'}}">${{r.price!==null?r.price.toFixed(0)+'\\u20ac':'N/A'}}</td>
    <td>-</td><td>-</td>`;
    tb.appendChild(tr);
  }});
}}

// --- Trains ---
function populateTrainSelect(){{
  const sel=document.getElementById('train-route-select');
  sel.innerHTML='';
  TIDS.forEach(id=>{{
    const opt=document.createElement('option');
    opt.value=id;opt.textContent=id+' — '+TD[id].label;
    sel.appendChild(opt);
  }});
  if(TIDS.length)renderTrainRoute(TIDS[0]);
}}

function renderTrainRoute(rid){{
  const d=TD[rid];if(!d)return;
  const tur=d.by_cabin.TURISTA||{{timestamps:[],prices:[]}};
  const pref=d.by_cabin.PREFERENTE||{{timestamps:[],prices:[]}};
  const tt=d.alerts.turista_max||30,pt=d.alerts.preferente_max||60;

  const tv=tur.prices.filter(p=>p!==null),pv=pref.prices.filter(p=>p!==null);
  const tbest=tv.length?Math.min(...tv):null,pbest=pv.length?Math.min(...pv):null;
  const tHit=tbest!==null&&tbest<=tt,pHit=pbest!==null&&pbest<=pt;
  document.getElementById('train-best').innerHTML=`
  <div class="best-card ${{tHit?'hit':''}}">
    <div class="best-label">Mejor Turista</div>
    <div class="best-price ${{tHit?'g':'r'}}">${{tbest!==null?tbest.toFixed(0)+'\\u20ac':'\\u2014'}}</div>
    <div class="best-info">Umbral: ${{tt}}\\u20ac</div>
    <div class="best-action"><a class="${{tHit?'btn-buy':'btn-wait'}}" href="https://www.renfe.com/es/es" target="_blank">${{tHit?'COMPRAR':'Esperar'}}</a></div>
  </div>
  <div class="best-card ${{pHit?'hit':''}}">
    <div class="best-label">Mejor Preferente</div>
    <div class="best-price ${{pHit?'g':'p'}}">${{pbest!==null?pbest.toFixed(0)+'\\u20ac':'\\u2014'}}</div>
    <div class="best-info">Umbral: ${{pt}}\\u20ac</div>
    <div class="best-action"><a class="${{pHit?'btn-buy':'btn-wait'}}" href="https://www.renfe.com/es/es" target="_blank">${{pHit?'COMPRAR':'Esperar'}}</a></div>
  </div>`;

  document.getElementById('tc1-title').textContent='Turista — Umbral '+tt+'\\u20ac';
  document.getElementById('tc2-title').textContent='Preferente — Umbral '+pt+'\\u20ac';
  if(tCharts[0])tCharts[0].destroy();if(tCharts[1])tCharts[1].destroy();
  tCharts[0]=mkChart('tc1',tur.timestamps,tur.prices,tt,'#3b82f6');
  tCharts[1]=mkChart('tc2',pref.timestamps,pref.prices,pt,'#a855f7');

  // Week grid (turista)
  const dateBest={{}};
  (d.week_best||[]).filter(w=>w.cabin==='TURISTA').forEach(w=>{{
    if(!dateBest[w.date]||w.price<dateBest[w.date])dateBest[w.date]=w.price;
  }});
  const dates=Object.keys(dateBest).sort();
  const dPrices=dates.map(dt=>dateBest[dt]);
  const dMin=dPrices.length?Math.min(...dPrices):0;
  const dMax=dPrices.length?Math.max(...dPrices):0;
  const dMid=dMin+(dMax-dMin)/3;const dHi=dMin+2*(dMax-dMin)/3;
  let dgHtml='';
  dates.forEach(dt=>{{
    const p=dateBest[dt];
    const cls=p<=dMid?'cheap':p<=dHi?'mid':'exp';
    dgHtml+=`<div class="week-cell ${{cls}}"><div class="wk">${{dt}}</div><div class="wp">${{p.toFixed(0)}}\\u20ac</div></div>`;
  }});
  document.getElementById('train-week-grid').innerHTML=dgHtml||'<p style="color:#64748b">Sin datos</p>';

  // History
  const allRows=[...tur.timestamps.map((t,i)=>({{ts:t,cabin:'Turista',price:tur.prices[i],date:tur.dates?tur.dates[i]:'',th:tt}})),
                  ...pref.timestamps.map((t,i)=>({{ts:t,cabin:'Preferente',price:pref.prices[i],date:pref.dates?pref.dates[i]:'',th:pt}}))];
  allRows.sort((a,b)=>b.ts.localeCompare(a.ts));
  const tb=document.getElementById('train-tbody');tb.innerHTML='';
  allRows.slice(0,100).forEach(r=>{{
    const ok=r.price!==null&&r.price<=r.th;
    const tr=document.createElement('tr');
    tr.innerHTML=`<td>${{r.ts}}</td><td>${{r.date}}</td>
    <td><span class="bg ${{r.cabin==='Preferente'?'bg-p':'bg-g'}}">${{r.cabin}}</span></td>
    <td style="font-weight:700;color:${{ok?'#4ade80':'#f87171'}}">${{r.price!==null?r.price.toFixed(0)+'\\u20ac':'N/A'}}</td>
    <td>-</td><td>-</td>`;
    tb.appendChild(tr);
  }});
}}

function mkChart(id,ts,pr,th,cl){{
  if(!ts||!ts.length)return null;
  return new Chart(document.getElementById(id),{{type:'line',data:{{labels:ts,datasets:[
    {{label:'Precio',data:pr,borderColor:cl,backgroundColor:cl+'20',fill:true,tension:.3,pointRadius:4,pointHoverRadius:7}},
    {{label:'Umbral '+th+'\\u20ac',data:Array(ts.length).fill(th),borderColor:'#fbbf24',borderDash:[6,4],pointRadius:0,fill:false}}
  ]}},options:{{responsive:true,plugins:{{legend:{{labels:{{color:'#94a3b8'}}}}}},scales:{{
    x:{{ticks:{{color:'#64748b',maxRotation:45}},grid:{{color:'#1e293b'}}}},
    y:{{ticks:{{color:'#64748b',callback:v=>v+'\\u20ac'}},grid:{{color:'#334155'}}}}
  }}}}}});
}}

populateFlightSelect();
populateTrainSelect();
</script></body></html>"""

    with open(DASHBOARD_FILE, "w") as f:
        f.write(html)

    # Also write to output/ for nginx serving
    OUTPUT_DIR.mkdir(exist_ok=True)
    output_file = OUTPUT_DIR / "index.html"
    with open(output_file, "w") as f:
        f.write(html)

    print(f"  Dashboard: {DASHBOARD_FILE}")
    return DASHBOARD_FILE
