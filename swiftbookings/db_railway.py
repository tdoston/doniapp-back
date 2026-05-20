"""Railway Postgres: URL tanlash va ulanish parametrlari."""

from __future__ import annotations

import os
from urllib.parse import quote_plus, urlparse


def _on_railway() -> bool:
    return bool(os.environ.get("RAILWAY_ENVIRONMENT", "").strip())


def resolve_database_url() -> str:
    """
    Backend (Railway): faqat private `DATABASE_URL` / `POSTGRES_PRIVATE_URL`.
    Lokal: `DATABASE_URL`, keyin `DATABASE_PUBLIC_URL`, keyin TCP proxy `POSTGRES_*`.
    """
    if _on_railway():
        for key in ("DATABASE_URL", "POSTGRES_PRIVATE_URL"):
            url = os.environ.get(key, "").strip()
            if url:
                return url
        return ""

    url = os.environ.get("DATABASE_URL", "").strip()
    if url:
        return url
    url = os.environ.get("DATABASE_PUBLIC_URL", "").strip()
    if url:
        return url

    host = os.environ.get("RAILWAY_TCP_PROXY_DOMAIN", "").strip()
    password = os.environ.get("POSTGRES_PASSWORD", "").strip()
    if host and password:
        user = os.environ.get("POSTGRES_USER", "postgres").strip()
        db = os.environ.get("POSTGRES_DB", "railway").strip()
        port = os.environ.get("RAILWAY_TCP_PROXY_PORT", "5432").strip()
        return (
            f"postgresql://{quote_plus(user)}:{quote_plus(password)}"
            f"@{host}:{port}/{db}?sslmode=require"
        )
    return ""


def database_config_from_url(url: str) -> dict:
    """Django DATABASES['default'] — Railway ichki tarmoqda SSL o‘chiriladi."""
    p = urlparse(url)
    path = (p.path or "").lstrip("/")
    host = (p.hostname or "127.0.0.1").lower()

    from urllib.parse import parse_qs

    q = parse_qs(p.query or "")
    ssl_vals = q.get("sslmode") or []
    sslmode = str(ssl_vals[0]).strip() if ssl_vals else os.environ.get("POSTGRES_SSLMODE", "").strip()

    # Railway private network (*.railway.internal) — SSL ishlatilmaydi
    if ".railway.internal" in host or host.endswith(".internal"):
        sslmode = "disable"
    elif not sslmode and "proxy.rlwy.net" in host:
        sslmode = "require"

    options: dict[str, str] = {"connect_timeout": str(int(os.environ.get("POSTGRES_CONNECT_TIMEOUT", "10")))}
    if sslmode:
        options["sslmode"] = sslmode

    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": path or "railway",
        "USER": p.username or "postgres",
        "PASSWORD": p.password or "",
        "HOST": p.hostname or "127.0.0.1",
        "PORT": str(p.port or 5432),
        "CONN_MAX_AGE": 0 if _on_railway() else int(os.environ.get("POSTGRES_CONN_MAX_AGE", "60")),
        "OPTIONS": options,
    }


def masked_db_target(url: str) -> str:
    p = urlparse(url)
    host = p.hostname or "?"
    port = p.port or 5432
    db = (p.path or "/").lstrip("/") or "?"
    return f"{host}:{port}/{db}"
