"""Deprecated startup seeder — disabled in Data Collector 2.0 (SEC-002)."""

from __future__ import annotations


def seed_users() -> None:
    """Automatic default admin seeding has been removed.

    Use `data-collector admin bootstrap --email <email>` instead.
    """
    raise RuntimeError(
        "Automatic default admin seeding is disabled (SEC-002). "
        "Use `data-collector admin bootstrap --email ...`."
    )
