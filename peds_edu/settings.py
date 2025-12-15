"""Django settings for peds_edu.

This project is designed to be deployed on AWS Ubuntu with MySQL.
Configuration is done primarily via environment variables.

Required env vars (minimum):
- DJANGO_SECRET_KEY
- DJANGO_DEBUG (0/1)
- DB_NAME, DB_USER, DB_PASSWORD, DB_HOST, DB_PORT
- APP_BASE_URL (e.g. https://edu.exampleclinic.com)
- SENDGRID_API_KEY, SENDGRID_FROM_EMAIL

Optional:
- ALLOWED_HOSTS (comma-separated)
- REDIS_URL (e.g. redis://localhost:6379/1)
"""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def env(name: str, default: str | None = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


SECRET_KEY = env("DJANGO_SECRET_KEY", "dev-insecure-change-me")
DEBUG = env("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [h.strip() for h in env("ALLOWED_HOSTS", "*").split(",") if h.strip()]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "accounts.apps.AccountsConfig",
    "catalog.apps.CatalogConfig",
    "sharing.apps.SharingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "peds_edu.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "sharing.context_processors.clinic_branding",
            ],
        },
    },
]

WSGI_APPLICATION = "peds_edu.wsgi.application"


# Database

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": env("DB_NAME", "peds_edu"),
        "USER": env("DB_USER", "peds_edu"),
        "PASSWORD": env("DB_PASSWORD", "Bv9ALOgzFszxDYso"),
        "HOST": env("DB_HOST", "127.0.0.1"),
        "PORT": env("DB_PORT", "3306"),
        "OPTIONS": {
            "charset": "utf8mb4",
        },
    }
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"


# Internationalization

LANGUAGE_CODE = "en"

# Languages supported by the patient pages and doctor sharing workflow
LANGUAGES = [
    ("en", "English"),
    ("hi", "Hindi"),
    ("te", "Telugu"),
    ("ml", "Malayalam"),
    ("mr", "Marathi"),
    ("kn", "Kannada"),
    ("ta", "Tamil"),
    ("bn", "Bengali"),
]
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True


# Static files

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"


DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"


# Sessions
# Keep users logged in for a long time ("Subsequent use should retain the session in browser")
SESSION_COOKIE_AGE = int(env("SESSION_COOKIE_AGE_SECONDS", str(60 * 60 * 24 * 90)))  # 90 days
SESSION_EXPIRE_AT_BROWSER_CLOSE = False
SESSION_SAVE_EVERY_REQUEST = True


# Security (set these to True/secure in production behind HTTPS)
CSRF_COOKIE_SECURE = env("CSRF_COOKIE_SECURE", "0") == "1"
SESSION_COOKIE_SECURE = env("SESSION_COOKIE_SECURE", "0") == "1"
SECURE_SSL_REDIRECT = env("SECURE_SSL_REDIRECT", "0") == "1"


# Email / SendGrid
APP_BASE_URL = env("APP_BASE_URL", "http://localhost:8000")
SENDGRID_API_KEY = env("SENDGRID_API_KEY", "")
SENDGRID_FROM_EMAIL = env("SENDGRID_FROM_EMAIL", "")


# Cache
REDIS_URL = os.getenv("REDIS_URL")
if REDIS_URL:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": REDIS_URL,
            "OPTIONS": {"CLIENT_CLASS": "django_redis.client.DefaultClient"},
            "TIMEOUT": int(env("CACHE_DEFAULT_TIMEOUT_SECONDS", "3600")),
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "peds-edu-locmem",
            "TIMEOUT": int(env("CACHE_DEFAULT_TIMEOUT_SECONDS", "3600")),
        }
    }

# How long the catalog JSON is cached (for doctor share screen)
CATALOG_CACHE_SECONDS = int(env("CATALOG_CACHE_SECONDS", str(60 * 60)))


# Logging (simple stdout)
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "root": {"handlers": ["console"], "level": "INFO"},
}
