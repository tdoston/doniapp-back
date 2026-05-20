# Railway diagnostika (doniapp-back + Postgres)

CLI bu mashinada login qilinmagan — loglarni **Railway Dashboard** dan oling.

## Hozirgi holat (tashqi tekshiruv)

| Servis | URL | Natija |
|--------|-----|--------|
| **Frontend** | doniapp-front-production.up.railway.app | **200** — ishlayapti |
| **Backend** | doniapp-back-production.up.railway.app/api/health | **502** — konteyner javob bermayapti |

502 = gunicorn `PORT` da tinglamayapti yoki konteyner **crash loop** (start skripti `exit 1`).

---

## Backend — logda ko‘rinadigan xatolar

### 1. `DATABASE_URL yo'q` / `Postgres URL yo'q`
- **Sabab:** Postgres backend bilan ulanmagan yoki faqat `POSTGRES_*` reference bor, `DATABASE_URL` inject qilinmagan.
- **Tuzatish:** Postgres → **Connect** → **doniapp-back**. Variables da `DATABASE_URL` yoki `POSTGRES_PRIVATE_URL` bo‘lsin.

### 2. `DB kutilyapti (12/12)` → `Postgres javob bermadi`
- **Sabab:** Postgres servisi **Crashed** / **Stopped** (7+ soat offline bo‘lishi mumkin).
- **Tuzatish:** Postgres servisi → **Restart** → yashil → backend **Redeploy**.

### 3. `failed to resolve host 'postgres.railway.internal'`
- **Build** bosqichida — normal (build tarmog‘ida DB yo‘q). **Start**da bo‘lsa — Postgres o‘chiq yoki noto‘g‘ri URL.

### 4. `SSL error` / `certificate verify failed` (ichki hostda)
- **Sabab:** `DATABASE_PUBLIC_URL` (TCP/proxy) backendda ishlatilmoqda, ichki hostda SSL kerak emas.
- **Tuzatish:** Backendda faqat **private** `DATABASE_URL` (`postgres.railway.internal`). `DATABASE_PUBLIC_URL` ni backend Variablesdan olib tashlang.

### 5. `pip: command not found` (build)
- **Sabab:** `builder = NIXPACKS` + `pip install` (eski config).
- **Tuzatish:** Hozirgi `railway.toml` — Railpack, `railway.sh build` faqat collectstatic.

### 6. Deploy **FAILED** (release bosqichi)
- **Sabab:** `releaseCommand` DB ga ulanmasdan yiqilgan (Postgres down).
- **Tuzatish:** Oxirgi kodda release olib tashlangan (`b3da010`); faqat **start** ishlaydi.

### 7. Start uzoq → healthcheck timeout
- **Sabab:** DB kutish (12×10s) + migrate + seed, keyin gunicorn.
- **Log:** `[railway] gunicorn` dan oldin to‘xtasa — migrate/seed xatosi.

---

## Postgres — logda ko‘rinadigan xatolar

| Holat (UI) | Ma’nosi |
|------------|---------|
| **Crashed** / **Failed** | Disk/memory limit, corrupt volume, yoki uzoq offline |
| **Out of memory** | Postgres RAM yetarli emas — plan yoki connection flood |
| **Too many connections** | Backend har restartda ko‘p ulanish (oldingi versiyalarda seed/bootstrap tsikli) |
| **Recovery mode** / **starting up** | Restartdan keyin 1–3 daqiqa kutish kerak |

**Tekshiruv:** Postgres → **Metrics** (CPU/RAM/Disk), **Logs** (oxirgi `FATAL` / `PANIC` qatorlari).

---

## To‘g‘ri deploy log ketma-ketligi

```
[railway] collectstatic          # build
[settings] DB → postgres.railway.internal:5432/railway
[railway] DB postgres.railway.internal:5432/railway
OK — PostgreSQL ...              # check_db
bootstrap_postgres_schema: already ready, skip
migrate / seed_initial_db: skip yoki OK
[railway] gunicorn :8080
```

Keyin: `curl .../api/health` → `{"ok":true,"db":true,"ready":true}`

---

## Tekshiruv buyruqlari (Railway → doniapp-back → Run)

```bash
python manage.py check_db
python manage.py migrate --noinput
```

`check_db` **FAIL** → Postgres yoki URL muammosi.
