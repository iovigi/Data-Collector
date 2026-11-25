"""API v1 Blueprint registration."""

from __future__ import annotations

from flask import Blueprint

from data_collector.api.v1.admin_ext import admin_ext_bp
from data_collector.api.v1.analytics import analytics_bp
from data_collector.api.v1.audit import audit_bp
from data_collector.api.v1.auth import auth_bp
from data_collector.api.v1.collections import collections_bp
from data_collector.api.v1.jobs import jobs_bp
from data_collector.api.v1.keys import keys_bp
from data_collector.api.v1.m11 import m11_bp
from data_collector.api.v1.mcp_access import mcp_access_bp
from data_collector.api.v1.projects import projects_bp
from data_collector.api.v1.records import records_bp
from data_collector.api.v1.workspaces import workspaces_bp


def create_v1_blueprint() -> Blueprint:
    v1 = Blueprint("api_v1", __name__, url_prefix="/api/v1")
    v1.register_blueprint(auth_bp)
    v1.register_blueprint(workspaces_bp)
    v1.register_blueprint(projects_bp)
    v1.register_blueprint(collections_bp)
    v1.register_blueprint(records_bp)
    v1.register_blueprint(jobs_bp)
    v1.register_blueprint(keys_bp)
    v1.register_blueprint(audit_bp)
    v1.register_blueprint(m11_bp)
    v1.register_blueprint(admin_ext_bp)
    v1.register_blueprint(analytics_bp)
    v1.register_blueprint(mcp_access_bp)
    return v1
