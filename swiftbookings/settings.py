import os
from pathlib import Path

import dj_database_url
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# ── Environment ──────────────────────────────────────────────────────────────
# DJANGO_ENV: "local" | "staging" | "production"
DJANGO_ENV = os.environ.get("DJANGO_ENV", "local").strip().lower()

DEBUG = DJANGO_ENV == "local"

SECRET_KEY = os.environ.get(
    "SECRET_KEY",
    "dev-only-insecure-secret-change-in-staging-and-production",
)

# ── Hosts ────────────────────────────────────────────────────────────────────
_raw_hosts = os.environ.get("ALLOWED_HOSTS", "127.0.0.1,localhost" if DEBUG else "").strip()
ALLOWED_HOSTS: list[str] = [h.strip() for h in _raw_hosts.split(",") if h.strip()]

_railway_public = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_public and _railway_public not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_public)
if DJANGO_ENV in ("staging", "production") and ".up.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".up.railway.app")

# ── Database ─────────────────────────────────────────────────────────────────
_db_url = (
    os.environ.get("DATABASE_URL", "").strip()
    or os.environ.get("DATABASE_PUBLIC_URL", "").strip()
)

if not _db_url:
    raise RuntimeError(
        "DATABASE_URL is not set. "
        "Link a Postgres service to this Railway service, or set DATABASE_URL in .env for local dev."
    )

DATABASES = {
    "default": dj_database_url.config(
        default=_db_url,
        conn_max_age=60,
        conn_health_checks=True,
        ssl_require=DJANGO_ENV in ("staging", "production"),
    )
}

# ── Apps ─────────────────────────────────────────────────────────────────────
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "corsheaders",
    "rest_framework",
    "api",
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

# ── Middleware ────────────────────────────────────────────────────────────────
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

# ── Localisation ──────────────────────────────────────────────────────────────
LANGUAGE_CODE = "uz"
TIME_ZONE = "Asia/Tashkent"
USE_I18N = True
USE_TZ = True

# ── Static ────────────────────────────────────────────────────────────────────
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

# ── CORS ─────────────────────────────────────────────────────────────────────
def _normalize_origin(o: str) -> str:
    raw = o.strip().rstrip("/")
    if not raw:
        return ""
    return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS: list[str] = [
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8081",
    "http://localhost:8081",
]
for _o in os.environ.get("CORS_EXTRA_ORIGINS", "").split(","):
    _norm = _normalize_origin(_o)
    if _norm and _norm not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(_norm)

CORS_ALLOWED_ORIGIN_REGEXES: list[str] = []
if DJANGO_ENV in ("staging", "production") and not os.environ.get("CORS_STRICT", "").strip():
    CORS_ALLOWED_ORIGIN_REGEXES = [r"^https://[a-zA-Z0-9.-]+\.up\.railway\.app$"]

# ── CSRF ──────────────────────────────────────────────────────────────────────
CSRF_TRUSTED_ORIGINS: list[str] = [
    "http://127.0.0.1:3001",
    "http://localhost:3001",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
]
for _o in os.environ.get("CSRF_TRUSTED_ORIGINS", "").split(","):
    _norm = _normalize_origin(_o)
    if _norm and _norm not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_norm)

if DJANGO_ENV in ("staging", "production"):
    CSRF_TRUSTED_ORIGINS += [
        "https://*.up.railway.app",
    ]

# ── Security (staging / production only) ─────────────────────────────────────
DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024
APPEND_SLASH = False

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_SSL_REDIRECT = os.environ.get("DJANGO_SECURE_SSL_REDIRECT", "1") == "1"
