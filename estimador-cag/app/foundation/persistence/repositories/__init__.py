"""Repositorios estrechos sobre la persistencia de la ingesta.

Cada repositorio envuelve una `AsyncSession` y expone solo las operaciones que necesita su
llamante; ningún tipo del ORM se filtra fuera.
"""

from app.foundation.persistence.repositories.jobs import Job, JobsRepository
from app.foundation.persistence.repositories.mappings import Mapping, MappingsRepository

__all__ = ["Job", "JobsRepository", "Mapping", "MappingsRepository"]
