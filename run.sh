#!/usr/bin/env bash
set -e

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$DIR"

if [ ! -d "venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv venv
    source venv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
else
    source venv/bin/activate
fi

export PYTHONPATH=.
echo "Starting SEO Link & Keyword Checker on http://localhost:8000"
exec uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
