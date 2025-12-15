"""ASGI config for peds_edu project."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "peds_edu.settings")

application = get_asgi_application()
