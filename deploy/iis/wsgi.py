"""IIS FastCGI entrypoint: ``WSGI_HANDLER = deploy.iis.wsgi.application``.

Reuses ``data_collector.app.create_app`` (via ``build_application``); configuration comes
from the env file named by ``DC_ENV_FILE`` (set in the site's web.config appSettings - a
path, never a secret).
"""

from data_collector.hosting.iis_app import build_application

application = build_application()
