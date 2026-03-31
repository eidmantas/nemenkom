# Installation Guide

This project runs from local `config.py`, local `secrets/`, and the active SQLite DB under
`services/database/`.

## Prerequisites

- Python `3.14+`
- Podman or Docker for containerized runs
- at least one AI provider key for PDF parsing
- Google Calendar service account credentials if you want calendar sync

## 1. Clone and Create Local Config

```bash
git clone <repository-url>
cd nemenkom
cp config.example.py config.py
```

`config.py` is intentionally ignored by git.

## 2. Prepare `secrets/`

All real secret files go into `secrets/`.

`secrets/` is ignored by git by default, except:

- `secrets/.gitkeep`
- `secrets/*.example`

### Required

#### `secrets/api_key.txt`

API key for protected API calls.

Example generator:

```bash
openssl rand -hex 32 > secrets/api_key.txt
```

#### `secrets/credentials.json`

Google Calendar service account JSON used by the calendar worker.

Important:

- this must be a service account JSON, not an OAuth client JSON
- the service account needs Calendar API access
- calendars that the worker updates must be accessible to that service account

### At least one AI provider key

The PDF parser needs at least one live AI provider:

- `secrets/groq_api_key.txt`
- `secrets/gemini_api_key.txt`
- `secrets/mistral_api_key.txt`
- `secrets/openrouter_api_key.txt`
- `secrets/huggingface_api_key.txt`

The provider/model order is configured in `config.py` via `AI_MODEL_ROTATION`.

### Expected shape

```text
secrets/
├── .gitkeep
├── api_key.txt
├── credentials.json
├── groq_api_key.txt
├── gemini_api_key.txt
├── mistral_api_key.txt
├── openrouter_api_key.txt
└── huggingface_api_key.txt
```

Only one AI key is required, but having more than one is strongly recommended for failover.

## 3. Install Dependencies

### Local venv

```bash
make venv-install
source venv/bin/activate
```

### Or manually

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

## 4. Verify Configuration

```bash
source venv/bin/activate
python -c "import config; print('config ok')"
```

If this fails, the error message usually tells you which secret file is missing.

## 5. Run Locally

### API / website

```bash
source venv/bin/activate
python services/api/app.py
```

Open `http://localhost:3333`.

### XLSX scraper

```bash
source venv/bin/activate
python services/scraper/main.py --force
```

### PDF scrapers

```bash
source venv/bin/activate
python services/scraper_pdf/main.py --source plastikas --force
python services/scraper_pdf/main.py --source stiklas --force
```

### Calendar worker

```bash
source venv/bin/activate
python services/calendar/worker.py
```

## 6. Run with Containers

```bash
make build
make up
```

The compose setup mounts:

- `./config.py:/app/config.py:ro`
- `./secrets:/app/secrets:ro`

So secrets and config stay on the host and are not baked into images.

## Common Checks

### Which database is active?

The app uses:

- `services/database/waste_schedule.db`

The root `waste_schedule.db` is only a manual snapshot/helper unless you explicitly copy it over.

### Is PDF continuity working?

Run the focused regression suite:

```bash
source venv/bin/activate
pytest -q tests/test_pdf_continuity.py tests/test_calendar_sync.py tests/test_one_calendar_per_group.py tests/test_calendar_ux_flow.py
```

### Are secrets ignored?

```bash
git check-ignore -v secrets/api_key.txt secrets/credentials.json
```

## Troubleshooting

### `No active AI providers configured`

- add at least one real AI key file under `secrets/`
- re-run `python -c "import config"`

### `credentials.json` errors

- confirm it is a service account JSON
- confirm `config.py` points at `secrets/credentials.json`

### PDF import is slow

That is normal for difficult provider cells. The parser retries across providers and may spend
several minutes on complex rows.

## Related Docs

- [README.md](README.md)
- [RELEASE.md](RELEASE.md)
- [services/ARCHITECTURE.md](services/ARCHITECTURE.md)
- [documentation/TESTING.md](documentation/TESTING.md)
