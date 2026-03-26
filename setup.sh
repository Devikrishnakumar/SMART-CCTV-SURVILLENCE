#!/bin/bash
# ─────────────────────────────────────────────
#  SMART-CCTV-SURVILLENCE — one-shot setup
#  Run from inside the project root
# ─────────────────────────────────────────────
set -e

echo ""
echo "╔══════════════════════════════════════╗"
echo "║   SMART-CCTV Setup                  ║"
echo "╚══════════════════════════════════════╝"
echo ""

# 1. Virtual env
if [ ! -d "venv" ]; then
  echo "[1/5] Creating virtual environment..."
  python3 -m venv venv
else
  echo "[1/5] venv already exists — skipping"
fi

source venv/bin/activate

# 2. Install deps
echo "[2/5] Installing dependencies..."
pip install -q -r requirements.txt
pip install -q aiosqlite greenlet

# 3. Vision deps (ultralytics for YOLOv11, opencv)
echo "[3/5] Installing vision dependencies..."
pip install -q ultralytics opencv-python-headless httpx

# 4. Alembic
echo "[4/5] Running migrations..."
# Stamp if tables already exist, otherwise upgrade
alembic upgrade head 2>/dev/null || alembic stamp head

# 5. Done
echo "[5/5] Done!"
echo ""
echo "  Start backend:  uvicorn app.main:app --reload --port 8000"
echo "  Start vision:   python3 vision/detector.py --camera-id <id> --source 0"
echo "  Swagger docs:   http://localhost:8000/docs"
echo ""
