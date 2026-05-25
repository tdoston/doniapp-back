import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
# Avvalo `django_backend/.env`, keyin loyiha ildizi `.env` (faqat hali bo'sh bo'lgan kalitlar)
load_dotenv(BASE_DIR / ".env")
load_dotenv(BASE_DIR.parent / ".env", override=False)

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-change-in-production")

DEBUG = os.environ.get("DJANGO_DEBUG", "0") == "1"

ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]
_railway_public = os.environ.get("RAILWAY_PUBLIC_DOMAIN", "").strip()
if _railway_public and _railway_public not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(_railway_public)
# Railway default URL: *.up.railway.app (Django — boshidagi nuqta bilan barcha subdomain)
if os.environ.get("RAILWAY_ENVIRONMENT", "").strip() and ".up.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(".up.railway.app")
# Railway deploy healthcheck: Host: healthcheck.railway.app
if os.environ.get("RAILWAY_ENVIRONMENT", "").strip() and "healthcheck.railway.app" not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append("healthcheck.railway.app")

from swiftbookings.db_railway import database_config_from_url, masked_db_target, resolve_database_url

_db_url = resolve_database_url()
if _db_url.startswith("postgresql://") or _db_url.startswith("postgres://"):
    DATABASES = {"default": database_config_from_url(_db_url)}
    if os.environ.get("RAILWAY_ENVIRONMENT", "").strip():
        print(f"[settings] DB → {masked_db_target(_db_url)} env=production", flush=True)
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
    "rest_framework",
    "api",
]

REST_FRAMEWORK = {
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": ["rest_framework.parsers.JSONParser"],
}

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
STATICFILES_STORAGE = (
    "django.contrib.staticfiles.storage.StaticFilesStorage"
    if DEBUG
    else "whitenoise.storage.CompressedStaticFilesStorage"
)

def _normalize_origin(origin: str) -> str:
    """Ensure env-provided origin has scheme for Django 4+ checks."""
    raw = origin.strip().rstrip("/")
    if not raw:
        return ""
    if raw.startswith("http://") or raw.startswith("https://"):
        return raw
    return f"https://{raw}"

CORS_ALLOW_ALL_ORIGINS = DEBUG
CORS_ALLOWED_ORIGINS = [
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8081",
    "http://localhost:8081",
    "http://127.0.0.1:8082",
    "http://localhost:8082",
    "https://doniapp-front-production.up.railway.app",
]
for _origin in os.environ.get("CORS_EXTRA_ORIGINS", "").split(","):
    _o = _normalize_origin(_origin)
    if _o and _o not in CORS_ALLOWED_ORIGINS:
        CORS_ALLOWED_ORIGINS.append(_o)

# Railway: frontend va backend alohida `*.up.railway.app` bo‘lsa, CORS ro‘yxatida bo‘lmasa
# brauzer `fetch`ni bloklaydi. `CORS_STRICT_RAILWAY=1` bo‘lsa regex qo‘llanmaydi.
CORS_ALLOWED_ORIGIN_REGEXES: list[str] = []
if os.environ.get("RAILWAY_ENVIRONMENT", "").strip() and os.environ.get("CORS_STRICT_RAILWAY", "").strip().lower() not in (
    "1",
    "true",
    "yes",
):
    CORS_ALLOWED_ORIGIN_REGEXES = [
        r"^https://[a-zA-Z0-9.-]+\.up\.railway\.app$",
    ]
# Lokal dev: ngrok URL har safar o‘zgarishi mumkin — DEBUG da regex (CORS_EXTRA_ORIGINS siz)
if DEBUG:
    CORS_ALLOWED_ORIGIN_REGEXES.extend(
        [
            r"^https://[a-zA-Z0-9-]+\.ngrok-free\.app$",
            r"^https://[a-zA-Z0-9-]+\.ngrok\.io$",
            r"^https://[a-zA-Z0-9-]+\.ngrok\.app$",
        ]
    )

CSRF_TRUSTED_ORIGINS = [
    "http://127.0.0.1:3001",
    "http://localhost:3001",
    "http://127.0.0.1:8080",
    "http://localhost:8080",
    "http://127.0.0.1:8081",
    "http://localhost:8081",
    "http://127.0.0.1:8082",
    "http://localhost:8082",
    "https://doniapp-front-production.up.railway.app",
]
for _origin in os.environ.get("CSRF_TRUSTED_EXTRA", "").split(","):
    _o = _normalize_origin(_origin)
    if _o and _o not in CSRF_TRUSTED_ORIGINS:
        CSRF_TRUSTED_ORIGINS.append(_o)

DATA_UPLOAD_MAX_MEMORY_SIZE = 15 * 1024 * 1024

# REST yo'llar: /api/board, /api/users/1, ...
APPEND_SLASH = False

if not DEBUG:
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    # Railway: SSL edge da; ichki healthcheck HTTP — redirect 301 healthcheckni sindiradi
    SECURE_SSL_REDIRECT = False
