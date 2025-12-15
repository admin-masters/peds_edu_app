#!/usr/bin/env bash
set -e

PROJECT_DIR=/home/ubuntu/peds_edu_app
VENV_DIR=/home/ubuntu/venv
PYTHON=$VENV_DIR/bin/python
PIP=$VENV_DIR/bin/pip
SERVICE_NAME=peds_edu   # matches /etc/systemd/system/peds_edu.service

cd "$PROJECT_DIR"

echo "[deploy] Ensuring venv exists..."
if [ ! -d "$VENV_DIR" ]; then
  python3 -m venv "$VENV_DIR"
fi

echo "[deploy] Installing requirements..."
$PIP install --upgrade pip
$PIP install -r requirements.txt

echo "[deploy] Running migrations..."
$PYTHON manage.py migrate --noinput

echo "[deploy] Collecting static files..."
$PYTHON manage.py collectstatic --noinput || true

echo "[deploy] Restarting gunicorn service..."
sudo systemctl restart "$SERVICE_NAME"

echo "[deploy] Done."
