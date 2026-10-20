"""Persistencia de la ingesta (sesión 6): trabajos de ingesta y mappings de seudónimos.

Comparte la base PostgreSQL del historial pero tiene su propia base declarativa y se migra con
Alembic. Los repositorios de `app.persistence.repositories` son la única puerta de acceso: ningún
tipo del ORM sale de ellos.
"""
