import os
from pathlib import Path
from urllib.parse import parse_qs, quote_plus, urlparse

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-in-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
_railway_public = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_public and _railway_public not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_public)

def _database_from_url(url: str) -> dict:
    if url.startswith("postgresql://") or url.startswith("postgres://"):
        p = urlparse(url)
        path = (p.path or "").lstrip("/")
        q = parse_qs(p.query or "")
        ssl_vals = q.get("sslmode") or []
        sslmode = str(ssl_vals[0]).strip() if ssl_vals else ""
        if not sslmode:
            sslmode = os.environ.get("POSTGRES_SSLMODE", "").strip()
        host_l = (p.hostname or "").lower()
        # Railway TCP proxy — URL da sslmode bo‘lmasa, odatda SSL talab qilinadi
        if not sslmode and "proxy.rlwy.net" in host_l:
            sslmode = "require"
        options: dict[str, str] = {}
        if sslmode:
            options["sslmode"] = sslmode
        return {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": path or "swift_bookings",
            "USER": p.username or "postgres",
            "PASSWORD": p.password or "postgres",
            "HOST": p.hostname or "127.0.0.1",
            "PORT": str(p.port or 5432),
            "CONN_MAX_AGE": 60,
            **({"OPTIONS": options} if options else {}),
        }
    return {}


# Railway: ichki tarmoqda `DATABASE_URL` (private). Lokal/tashqi: `DATABASE_PUBLIC_URL` yoki
# `RAILWAY_TCP_PROXY_DOMAIN` + `RAILWAY_TCP_PROXY_PORT` + `POSTGRES_*`.
_db_url = (
    os.environ.get("DATABASE_URL", "").strip()
    or os.environ.get("DATABASE_PUBLIC_URL", "").strip()
)
_tcp_host = os.environ.get("RAILWAY_TCP_PROXY_DOMAIN", "").strip()
_tcp_port = os.environ.get("RAILWAY_TCP_PROXY_PORT", "").strip()
_pg_user = os.environ.get("POSTGRES_USER", "postgres").strip()
_pg_pass = os.environ.get("POSTGRES_PASSWORD", "").strip()
_pg_db = os.environ.get("POSTGRES_DB", "railway").strip()
if not _db_url and _tcp_host and _pg_pass:
    port = _tcp_port or "5432"
    _db_url = (
        f"postgresql://{quote_plus(_pg_user)}:{quote_plus(_pg_pass)}"
        f"@{_tcp_host}:{port}/{_pg_db}?sslmode=require"
    )
if _db_url.startswith("postgresql://") or _db_url.startswith("postgres://"):
    DATABASES = {"default": _database_from_url(_db_url)}
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("POSTGRES_DB", "swift_bookings"),
            "USER": os.environ.get("POSTGRES_USER", "postgres"),
            "PASSWORD": os.environ.get("POSTGRES_PASSWORD", "postgres"),
            "HOST": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            "PORT": os.environ.get("POSTGRES_PORT", "5432"),
            "CONN_MAX_AGE": int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
            "OPTIONS": {
                "sslmode": os.environ.get("POSTGRES_SSLMODE", "prefer"),
            },
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
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "api.middleware.DatabaseUnavailableMiddleware",
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
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

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

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
