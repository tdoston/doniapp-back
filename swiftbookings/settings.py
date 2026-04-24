import os
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-in-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = os.environ.get("DJANGO_ALLOWED_HOSTS", "*").split(",")

# SQLite fayli Django loyiha ichida. BASE_DIR = django_backend/
_DEFAULT_SQLITE = BASE_DIR / "data" / "swift_bookings.sqlite"


def _database_from_url(url: str) -> dict:
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        p = urlparse(url)
        path = (p.path or "").lstrip("/")
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": path or "swift_bookings",
            "USER": p.username or "postgres",
            "PASSWORD": p.password or "postgres",
            "HOST": p.hostname or "127.0.0.1",
            "PORT": str(p.port or 5432),
            "CONN_MAX_AGE": 60,
        }
    return {}


_db_url = os.environ.get("DATABASE_URL", "").strip()
if _db_url.startswith("postgresql://") or _db_url.startswith("postgres://"):
    DATABASES = {"default": _database_from_url(_db_url)}
else:
    sqlite_path = os.environ.get("SQLITE_PATH", str(_DEFAULT_SQLITE))
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": sqlite_path,
        }
    }

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "api",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "swiftbookings.urls"

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
            ],
        },
    },
]

WSGI_APPLICATION = "swiftbookings.wsgi.application"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8081",
    "http://localhost:8081",
    "http://127.0.0.1:8082",
    "http://localhost:8082",
]
for _origin in os.environ.get("CORS_EXTRA_ORIGINS", "").split(","):
    _o = _origin.strip()
    if _o and _o not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(_o)

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:3001",
    "http://localhost:3001",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8081",
    "http://localhost:8081",
    "http://127.0.0.1:8082",
    "http://localhost:8082",
]
for _origin in os.environ.get("CSRF_TRUSTED_EXTRA", "").split(","):
    _o = _origin.strip()
    if _o and _o not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_o)

DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

# REST yo'llar: /api/board, /api/users/1, ...
APPEND_SLASH = False
