#!/bin/bash
# Redegal Travel Monitor — Setup script
# Configures venv, dependencies, Playwright, and cron

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo ""
echo "  ================================================"
echo "  Redegal Travel Monitor — Setup"
echo "  ================================================"
echo ""

# 1. Virtual environment
if [ ! -d "venv" ]; then
    echo "  [1/4] Creating virtual environment..."
    python3 -m venv venv
else
    echo "  [1/4] Virtual environment exists."
fi

# 2. Dependencies
echo "  [2/4] Installing dependencies..."
venv/bin/pip install -q --upgrade pip
venv/bin/pip install -q -r requirements.txt

# 3. Playwright browsers
echo "  [3/4] Installing Playwright Chromium..."
venv/bin/python -m playwright install chromium 2>/dev/null || \
    venv/bin/python -m playwright install --with-deps chromium 2>/dev/null || \
    echo "  WARNING: Playwright install failed. Run manually: venv/bin/python -m playwright install chromium"

# 4. Data directory
mkdir -p data

# 5. Migrate old CSV if present
if [ -f "prices.csv" ] && [ ! -f "data/flights.csv" ]; then
    echo "  Migrating old prices.csv..."
    venv/bin/python -c "from travel_monitor.storage import migrate_old_csv; migrate_old_csv()"
fi

# 6. Cron job (every 2 hours)
CRON_CMD="0 */2 * * * cd $SCRIPT_DIR && venv/bin/python monitor.py --daemon >> $SCRIPT_DIR/monitor.log 2>&1"
EXISTING=$(crontab -l 2>/dev/null || true)

if echo "$EXISTING" | grep -q "travel-monitor\|flight-monitor"; then
    echo "  [4/4] Cron job already configured."
else
    echo "  [4/4] Setting up cron job (every 2 hours)..."
    # Remove old flight-monitor cron if exists
    CLEAN=$(echo "$EXISTING" | grep -v "flight-monitor" || true)
    (echo "$CLEAN"; echo "# Redegal Travel Monitor"; echo "$CRON_CMD") | crontab -
    echo "  Cron installed."
fi

echo ""
echo "  Setup complete!"
echo ""
echo "  Commands:"
echo "    cd $SCRIPT_DIR"
echo "    venv/bin/python monitor.py                  # All routes, single check"
echo "    venv/bin/python monitor.py --route VGO-MEX  # Single route"
echo "    venv/bin/python monitor.py --flights        # Only flights"
echo "    venv/bin/python monitor.py --trains         # Only trains"
echo "    venv/bin/python monitor.py --dashboard      # Regenerate dashboard"
echo "    venv/bin/python monitor.py --daemon         # Continuous mode"
echo ""
