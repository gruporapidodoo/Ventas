"""Configuracion - usa variables de entorno."""
import os
from pathlib import Path

# Cargar .env si existe (desarrollo local)
env_file = Path(__file__).parent / ".env"
if env_file.exists():
    for line in env_file.read_text().strip().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

ODOO_URL = os.environ.get("ODOO_URL", "https://pestbuster.odoo.com")
ODOO_DB = os.environ.get("ODOO_DB", "psdc-inc-pestbuster-prod-20747552")

# Credenciales: DEBEN estar en variables de entorno en produccion
ODOO_USER = os.environ["ODOO_USER"]
ODOO_PASSWORD = os.environ["ODOO_PASSWORD"]

FLASK_HOST = "0.0.0.0"
FLASK_PORT = int(os.environ.get("PORT", 5000))
FLASK_DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

SECRET_KEY = os.environ.get("SECRET_KEY", "cambiar-en-produccion-ventas-dash-2026")
