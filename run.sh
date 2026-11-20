#!/usr/bin/env bash
set -e
cd "$(dirname "$0")/backend"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
exec .venv/bin/python -c "
import uvicorn
from app.config import load_config
c = load_config()
uvicorn.run('app.main:app', host=c.host, port=c.port, log_level='info')"
