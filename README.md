# Bulk Certificate Generator

A backend API that accepts **one request containing many recipients**, generates a PDF
certificate for each valid recipient from a single predefined template, tracks progress,
and lets the client retrieve the results (individually or as one ZIP).

**Stack:** Python 3.10+ · FastAPI · SQLAlchemy 2 · SQLite (any SQL DB works) · ReportLab (PDF) · pytest

---

## 1. Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 2. Run the application

```bash
uvicorn app.main:app --reload
```

- API: <http://127.0.0.1:8000>
- Interactive docs (Swagger UI): <http://127.0.0.1:8000/docs>
- Tables are created automatically on startup (SQLite file `certgen.db`, PDFs in `storage/certificates/`).

Optional environment variables:

| Variable                 | Default                  | Meaning                                                       |
| ------------------------ | ------------------------ | ------------------------------------------------------------- |
| `DATABASE_URL`           | `sqlite:///./certgen.db` | Any SQLAlchemy URL (e.g. PostgreSQL)                          |
| `STORAGE_DIR`            | `./storage/certificates` | Where PDFs are written                                        |
| `PROCESSING_MODE`        | `background`             | `background` (async worker threads) or `inline` (synchronous) |
| `WORKER_THREADS`         | `2`                      | Number of jobs processed concurrently                         |
| `MAX_RECIPIENTS_PER_JOB` | `5000`                   | Max recipients per request                                    |

## 3. Run the tests

```bash
pytest
```

Tests use a temporary SQLite DB and temp storage, and run jobs inline so they are deterministic
(there is also one test that exercises real background processing).

---

## 4. API usage

| Method | Path                                                           | Purpose                                                                      |
| ------ | -------------------------------------------------------------- | ---------------------------------------------------------------------------- |
| `POST` | `/api/v1/jobs`                                                 | Submit a bulk request → `202 Accepted` + job                                 |
| `GET`  | `/api/v1/jobs/{job_id}`                                        | Status + progress                                                            |
| `GET`  | `/api/v1/jobs`                                                 | List jobs (`limit`, `offset`, `status`)                                      |
| `GET`  | `/api/v1/jobs/{job_id}/certificates`                           | Per-recipient results (`status=success\|failed\|pending`, `limit`, `offset`) |
| `GET`  | `/api/v1/jobs/{job_id}/certificates/{certificate_id}/download` | One PDF                                                                      |
| `GET`  | `/api/v1/jobs/{job_id}/download`                               | ZIP of all PDFs + `manifest.csv`                                             |
| `GET`  | `/health`                                                      | Liveness check                                                               |

### Submit a generation request

```bash
curl -X POST http://127.0.0.1:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d @samples/sample_request.json
```

### Retrieve generated certificates

```bash
# One certificate (use the download_url from the listing)
curl -OJ http://127.0.0.1:8000/api/v1/jobs/<job_id>/certificates/<certificate_id>/download

# Everything as a ZIP (only once the job has finished; includes manifest.csv)
curl -OJ http://127.0.0.1:8000/api/v1/jobs/<job_id>/download
```
