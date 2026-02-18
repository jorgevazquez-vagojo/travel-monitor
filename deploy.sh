#!/bin/bash
# Deploy Travel Monitor to remote server
# Server: 37.27.92.122 (same as Jorge Copilot bot)

set -e

SERVER="root@37.27.92.122"
REMOTE_DIR="/opt/travel-monitor"

echo ""
echo "  ================================================"
echo "  Deploying Travel Monitor to $SERVER"
echo "  ================================================"
echo ""

# 1. Create remote directory
echo "  [1/5] Creating remote directory..."
ssh $SERVER "mkdir -p $REMOTE_DIR/travel_monitor/scrapers $REMOTE_DIR/data"

# 2. Sync files (exclude venv, data, screenshots, git)
echo "  [2/5] Syncing files..."
rsync -avz --delete \
    --exclude 'venv/' \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude 'data/*.csv' \
    --exclude 'screenshot.png' \
    --exclude 'test_*.png' \
    --exclude 'debug_page.txt' \
    --exclude 'monitor.log' \
    --exclude 'dashboard.html' \
    --exclude 'prices.csv' \
    --exclude '.git/' \
    --exclude '.DS_Store' \
    --exclude 'deploy.sh' \
    ./ $SERVER:$REMOTE_DIR/

# 3. Run remote setup
echo "  [3/5] Running remote setup..."
ssh $SERVER "cd $REMOTE_DIR && bash setup.sh"

# 4. Setup systemd service for daemon mode
echo "  [4/5] Setting up systemd service..."
ssh $SERVER "cat > /etc/systemd/system/travel-monitor.service << 'SVCEOF'
[Unit]
Description=Redegal Travel Monitor
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/travel-monitor
ExecStart=/opt/travel-monitor/venv/bin/python monitor.py --daemon
Restart=always
RestartSec=60
StandardOutput=append:/opt/travel-monitor/monitor.log
StandardError=append:/opt/travel-monitor/monitor.log

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable travel-monitor
systemctl restart travel-monitor"

# 5. Verify
echo "  [5/5] Verifying..."
ssh $SERVER "systemctl status travel-monitor --no-pager -l | head -20"

echo ""
echo "  Deploy complete!"
echo "  Service: systemctl status travel-monitor"
echo "  Logs: ssh $SERVER 'tail -f /opt/travel-monitor/monitor.log'"
echo ""
