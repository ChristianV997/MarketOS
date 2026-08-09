#!/bin/bash
# MarketOS MVP Runner

set -e

echo "🚀 MarketOS Dropship MVP Launcher"
echo ""

# Check if this is the first run
if [ ! -f ~/.marketos/credentials.json ]; then
    echo "📋 No credentials found. Starting setup wizard..."
    echo ""
    python -m backend.cli_setup
    echo ""
fi

# Show configuration status
echo "✓ Configuration Status:"
python -c "
from backend.config import list_configured_services
services = list_configured_services()
for service, ready in sorted(services.items()):
    icon = '✓' if ready else '✗'
    status = 'Ready' if ready else 'Dry-run'
    print(f'  {icon} {service.upper()}: {status}')
"

echo ""
read -p "Ready to launch? (yes/no) [yes]: " -r choice
choice=${choice:-yes}

if [[ ! $choice =~ ^[Yy] ]]; then
    echo "Launch cancelled"
    exit 0
fi

echo ""
echo "🎯 Starting first dropship cycle..."
python -c "
import json
from backend.dropship import run_dropship_cycle

result = run_dropship_cycle(max_products=3, budget_daily=50.0)

print('')
print('Dropship Cycle Results:')
print(f'  Status: {result[\"status\"]}')
print(f'  Discovered: {result[\"discovered\"]} products')
print(f'  Validated: {result[\"validated\"]} products')
print(f'  Green: {result[\"green\"]} ready for launch')
print(f'  Launched: {result[\"launched\"]} campaigns')
print(f'  Duration: {result[\"duration_s\"]}s')
print('')

if result['status'] == 'ok':
    print('✓ MVP is running successfully!')
    print('')
    print('📊 Next steps:')
    print('  1. View campaign details: cat state/dropship.json | python -m json.tool')
    print('  2. Check costs: curl http://localhost:8000/api/dropship/costs/summary')
    print('  3. Monitor dashboard: streamlit run backend/monitoring/streamlit_dashboard.py')
    print('  4. Run orchestrator: python -m orchestrator.main')
"

echo ""
echo "📚 For more information, see MVP_STARTUP_GUIDE.md"
