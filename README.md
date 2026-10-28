# 11 · shortener

URL shortener with click analytics on FastAPI + SQLite.

## Run

```bash
uvicorn shortener.api:create_app --factory
```

## Test

```bash
pytest projects/11-url-shortener -q
```

## What it demonstrates

- SSRF and XSS defence: `javascript:`/`data:`/`file:` rejected, local hosts blocked
- `secrets` for codes, unique index for idempotent re-shortening
- 302 (not 301) so analytics are not defeated by the browser cache
- Visit rows keep referrer and user-agent for attribution
