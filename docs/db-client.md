# DB Client Library (`libs/db-client`)

Thin sync wrapper around a psycopg3 `ConnectionPool` for PostgreSQL. Used by the server to store targets and competitor config.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| `DATABASE_URL` | PostgreSQL DSN, e.g. `postgresql://haidilao:haidilao_dev@localhost:5432/haidilao` |
| **PostgreSQL** | Run via Docker (see below) or any external PostgreSQL 16+ instance |
| `psycopg[binary]` | Installed automatically via uv workspace |
| `psycopg-pool` | Installed automatically via uv workspace |

---

## Docker Setup

```bash
# Start PostgreSQL (detached)
docker compose -f docker/docker-compose.yml up -d

# Stop
docker compose -f docker/docker-compose.yml down

# Reset (destroys all data)
docker compose -f docker/docker-compose.yml down -v
docker compose -f docker/docker-compose.yml up -d
```

Default credentials (override with `POSTGRES_PASSWORD` env var):
- Host: `localhost:5432`
- Database: `haidilao`
- User: `haidilao`
- Password: `haidilao_dev`

`DATABASE_URL` for `.env`:
```
DATABASE_URL=postgresql://haidilao:haidilao_dev@localhost:5432/haidilao
```

---

## Database Class API

```python
from db_client import Database

# Read DATABASE_URL from environment
db = Database()

# Explicit DSN
db = Database(dsn="postgresql://...")

# Context manager (auto-closes pool)
with Database() as db:
    rows = db.fetchall("SELECT * FROM store_targets WHERE month_key = %s", ("2026-03",))
```

| Method | Description |
|--------|-------------|
| `execute(sql, params=None)` | Run a statement, discard result |
| `fetchone(sql, params=None)` | Return first row as `dict` or `None` |
| `fetchall(sql, params=None)` | Return all rows as `list[dict]` |
| `transaction()` | Context manager — yields a `Connection`, commits on exit, rolls back on exception |
| `close()` | Close the connection pool |

All methods raise `DBQueryError` on SQL errors.

### Errors

| Exception | When |
|-----------|------|
| `DBConnectionError` | `DATABASE_URL` not set, or pool failed to open |
| `DBQueryError` | SQL execution failed |

Both inherit from `DBError`.

---

## Migration System

Migrations are plain `.sql` files run in alphabetical order. Applied filenames are tracked in a `_migrations` table.

```python
from pathlib import Path
from db_client import Database
from db_client.migrations import run_migrations

with Database() as db:
    run_migrations(db, Path("server/migrations"))
```

- Idempotent — already-applied files are skipped.
- Each migration runs in its own transaction; failure rolls back only that migration.
- The server calls `maybe_run_migrations()` automatically at startup (no-op if `DATABASE_URL` is not set).

### Schema (managed by migrations)

| Table | Purpose |
|-------|---------|
| `store_targets` | Monthly revenue + turnover rate targets per store |
| `store_competitors` | Store → competitor store mappings |
| `admin_users` | Lark users who have logged into the admin UI |
| `_migrations` | Migration tracking (managed by runner) |

---

## Module Layout

```
libs/db-client/
└── src/db_client/
    ├── __init__.py      # re-exports Database, DBError hierarchy
    ├── client.py        # Database implementation
    ├── migrations.py    # run_migrations()
    ├── pool.py          # ConnectionPool helpers
    └── errors.py        # DBError, DBConnectionError, DBQueryError
```
