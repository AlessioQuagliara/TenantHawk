# =============================================================================
# backend/app/core/templates.py
# =============================================================================

from fastapi.templating import Jinja2Templates
from datetime import datetime

templates = Jinja2Templates(directory="app/templates")

# Aggiungi funzioni e filtri globali a Jinja
templates.env.globals['now'] = datetime.now