# wsgi.py — WSGI entry point for gunicorn in production
# Usage: gunicorn wsgi:app
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from web_app import app
