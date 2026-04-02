# Railway Option B (Dashboard + Cron Worker)

## Ziel
Du willst:
1. Events einreichen und freigeben über das **Web-Dashboard**
2. Das eigentliche „Posting“ per **Railway Cron/Worker** automatisieren

Für den aktuellen MVP gilt: **MOCK_MODE = 1** (keine externen APIs nötig).

## Services / Templates
Im Repo gibt es dafür zwei Templates:

- `railway-dashboard.json` → Dashboard-Service (`uvicorn web.app:app`)
- `railway.json` → Worker-Service (`python worker.py --post`)

### Wichtig: `railway up` und die root-`railway.json`

Die CLI **`railway up`** packt immer die **root-`railway.json`** ins Image — die ist für den **Worker** (`python worker.py --post`).  
Wenn du das **Dashboard** per CLI deployen willst, kurz die Dashboard-Config einspielen:

```bash
./scripts/railway_up_dashboard.sh "deploy message"
```

Der Worker wie gewohnt:

```bash
railway up -s gifhorn-worker -c -y -m "worker update"
```

*(GitHub-Deploy: im Railway-Dashboard pro Service die **Config-Datei** setzen — `railway-dashboard.json` vs. `railway.json`.)*

## 1) Dashboard-Service einrichten

### StartCommand
Siehe `railway-dashboard.json`.

### Env Vars (Minimum)
- `DATABASE_URL` = Railway Postgres URL (empfohlen)
- `MOCK_MODE=1`
- `SCRAPERS_ENABLED=0`
- `DASHBOARD_USER` (optional, default `admin`)
- `DASHBOARD_PASSWORD` = langes Passwort
- **Email-Flyer (empfohlen, wenn Gmail + Anhänge):**
  - Im Railway-Dashboard-Service: **Volume** anlegen, Mount-Pfad **`/app/email_attachments`**
  - `EMAIL_ATTACHMENT_STORAGE_PATH=/app/email_attachments` (entspricht dem Default in `config.py`)
  - `PUBLIC_IMAGE_BASE_URL=https://<dein-dashboard-host>/flyers` damit Meta öffentliche Bild-URLs bekommt

### Zugriffsweg
Öffne die Railway URL → Basic-Auth (User/Passwort) → Formular „Event einreichen“.

## 2) Worker-Service einrichten (Cron)

### StartCommand
Siehe `railway.json` (Standard: `python worker.py --post`).

### Env Vars (Minimum)
- `DATABASE_URL` = gleiche Railway Postgres URL wie im Dashboard
- `MOCK_MODE=1`
- `SCRAPERS_ENABLED=0`

### Cron Schedule
Railway Cron nutzt UTC.

Wenn du in **Europe/Berlin** (CET/CEST) z. B. um 19:00/20:00 posten willst:
- plane grob mit UTC um **1–2 Stunden Versatz** (DST beachten)

Für den MVP reicht es, testweise öfter auszuführen (z. B. alle 5–15 Minuten), bis du siehst, dass `posted_at` gesetzt wird.

Beispiel (UTC):
- `10 19 * * *` = täglich 19:10 UTC

Wichtig: Der Cron-Service muss nach der Arbeit **sofort terminieren** — `worker.py` ist so gebaut.

## Test-Flow (ohne externe APIs)
1. Im Dashboard `POST /submit`: Event einreichen
2. Im Dashboard „Freigeben“ klicken (`approved_for_social = true`)
3. Worker läuft → setzt `posted_at`

## Nächster Ausbau (wenn MVP läuft)
- Telegram wieder aktivieren (realer Freigabe-Flow)
- Scraper einschalten (`SCRAPERS_ENABLED=1`)
- Optional: echte Instagram/Facebook Posting-Calls

