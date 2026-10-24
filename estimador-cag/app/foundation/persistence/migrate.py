"""Aplica las migraciones Alembic (`alembic upgrade head`) al arrancar el contenedor de la API.

    python -m app.foundation.persistence.migrate

Sin `DATABASE_URL` no hace nada: la API funciona sin base de datos (historial e ingesta desactivados).
Se ejecuta antes de `uvicorn`, de modo que las tablas existan cuando la API acepta solicitudes.
"""

import sys
from pathlib import Path

from alembic.config import Config

from alembic import command
from app.config import get_settings

ALEMBIC_INI = Path(__file__).resolve().parents[3] / "alembic.ini"


def upgrade_to_head() -> bool:
    """Aplica las migraciones pendientes; devuelve `False` si no hay base de datos configurada."""
    if not get_settings().database_url:
        return False
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("script_location", str(ALEMBIC_INI.parent / "alembic"))
    command.upgrade(config, "head")
    return True


def _main() -> int:
    if upgrade_to_head():
        print("Migraciones aplicadas (alembic upgrade head).")
    else:
        print("DATABASE_URL no definida: se omiten las migraciones.")
    return 0


if __name__ == "__main__":
    sys.exit(_main())
