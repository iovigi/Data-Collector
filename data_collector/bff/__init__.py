"""IIS-native Admin UI hosting: Python BFF (sessions/CSRF/allowlisted API) + SPA serving."""

from __future__ import annotations

from flask import Flask

from data_collector.bff.routes import register_bff
from data_collector.bff.spa import register_spa


def register_iis_ui_and_bff(app: Flask, dist_dir: str) -> None:
    register_bff(app)
    register_spa(app, dist_dir)
