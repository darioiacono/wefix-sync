#!/bin/bash
set -e

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  🔧 WeFix Sync — Setup & Run"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Controlla Python 3
if ! command -v python3 &>/dev/null; then
  echo "❌ Python 3 non trovato. Installalo da https://python.org"
  exit 1
fi

# Crea virtualenv se non esiste
if [ ! -d "venv" ]; then
  echo "📦 Creazione ambiente virtuale..."
  python3 -m venv venv
fi

source venv/bin/activate

echo "📥 Installazione dipendenze..."
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "🎭 Installazione Playwright browser..."
playwright install chromium

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  ✅ Setup completato!"
echo "  🌐 Apri: http://localhost:5000"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

python3 app.py
