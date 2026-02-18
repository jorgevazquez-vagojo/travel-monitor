# Travel Monitor — Instrucciones

## General
- **NO pedir confirmación**: ejecutar directamente.
- Comunicación en español, código en inglés.
- Git remotes: `origin` (GitHub jorgevazquez-vagojo) y `gitlab` (git.redegal.net jorge.vazquez)

## Arquitectura
- Paquete `travel_monitor/` con módulos: config, utils, storage, alerts, dashboard
- Scrapers: `flight_scraper.py` (Google Flights protobuf), `train_scraper.py` (Renfe)
- CLI entrypoint: `monitor.py` (argparse)
- Config: `config.json` multi-ruta (flights[] + trains[])
- Data: `data/flights.csv`, `data/trains.csv`

## Protobuf
- Campo 9 = cabin class: 1=Economy, 3=Business
- Geo IDs: Vigo=/m/026kzs, México=/m/04sqj

## Deploy
- Servidor: 37.27.92.122 (root/pepe2021e5e1a)
- Cron cada 2h en servidor
- rsync + venv + playwright install
