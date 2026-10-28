#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "venv" ]; then
    echo "Creando entorno virtual..."
    python3 -m venv venv
    ./venv/bin/pip install --upgrade pip
    ./venv/bin/pip install -r requirements.txt
fi

echo "========================================================="
echo "   EconoMetrics AI - Evaluador de Rentabilidad"
echo "   Iniciando servidor FastAPI en http://0.0.0.0:8000"
echo "========================================================="

./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
