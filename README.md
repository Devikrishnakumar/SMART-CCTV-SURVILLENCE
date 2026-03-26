# 🚨 Emergency Detection & Dispatch API

Production-ready FastAPI backend for AI-powered emergency detection and dispatch.

## Architecture

```
YOLO Vision Module  →  POST /ai/report
                              ↓
                     Confidence Check (≥0.65)
                              ↓
                     Store Incident (PostgreSQL)
                              ↓
              ┌───────────────┴────────────────┐
              ↓                                ↓
     WebSocket Broadcast              Notify Emergency Services
     (/ws/alerts)                     (Ambulance / Police)
```

## Quick Start

```bash
# 1. Copy env file
cp .env.example .env
# Edit .env: set SECRET_KEY, ADMIN_PASSWORD, etc.

# 2. Start everything
docker-compose up --build

# 3. Run migrations (first time)
docker-compose run --rm migrate

# API docs available at:
open http://localhost:8000/docs
```

## Default Admin Credentials
- Username: `admin`
- Password: `Admin@12345!`
- ⚠️ Change immediately via `/auth/users` (admin only)

---

## API Reference

### Authentication

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/auth/login` | None | Get JWT token |
| POST | `/auth/users` | Admin | Create user |
| GET  | `/auth/me` | Any | Current user info |

**Login example:**
```bash
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "Admin@12345!"}'
```

### Cameras

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/cameras` | Operator+ | List cameras |
| GET | `/cameras/{id}` | Operator+ | Get camera |
| POST | `/cameras` | Admin | Create camera |

### Incidents

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/incidents` | Operator+ | Create incident |
| GET | `/incidents` | Operator+ | List (filterable) |
| GET | `/incidents/{id}` | Operator+ | Get incident |
| PUT | `/incidents/{id}/verify` | Operator+ | Verify incident |
| PUT | `/incidents/{id}/dispatch` | Dispatcher+ | Dispatch unit |
| PUT | `/incidents/{id}/resolve` | Dispatcher+ | Resolve incident |

**Query params for GET /incidents:**
- `status`: pending | verified | dispatched | resolved | closed
- `camera_id`: UUID
- `limit`: 1-200 (default 50)
- `offset`: pagination offset

### AI Integration

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/ai/report` | None* | Report AI detection |

*Secure in production with `X-AI-Module-Key` header (see routes/ai.py)

**Request body:**
```json
{
  "type": "accident",
  "confidence": 0.87,
  "camera_id": "uuid-here",
  "snapshot_url": "https://storage/snap.jpg",
  "video_clip_url": "https://storage/clip.mp4"
}
```

### WebSocket

Connect: `ws://localhost:8000/ws/alerts?token=<jwt>`

**Events received:**
```json
// New incident
{"event": "new_incident", "incident_id": "...", "type": "accident", "confidence": 0.87, ...}

// Status update
{"event": "incident_updated", "incident_id": "...", "status": "dispatched", "by": "dispatcher1"}
```

---

## Alert Logic

| Incident Type | Services Notified |
|--------------|-------------------|
| `accident` | Ambulance + Police |
| `violence` | Police |
| `fallen_person` | Ambulance |

---

## Role Permissions

| Endpoint | Operator | Dispatcher | Admin |
|----------|----------|------------|-------|
| View incidents/cameras | ✅ | ✅ | ✅ |
| Verify incident | ✅ | ✅ | ✅ |
| Dispatch incident | ❌ | ✅ | ✅ |
| Resolve incident | ❌ | ✅ | ✅ |
| Create cameras | ❌ | ❌ | ✅ |
| Create users | ❌ | ❌ | ✅ |

---

## Project Structure

```
app/
├── main.py              # FastAPI app + lifespan
├── config.py            # Settings (pydantic-settings)
├── database.py          # Async SQLAlchemy engine
├── models.py            # SQLAlchemy ORM models
├── schemas.py           # Pydantic request/response models
├── auth/
│   ├── security.py      # JWT + bcrypt
│   └── dependencies.py  # OAuth2 dependency + RBAC
├── routes/
│   ├── auth.py          # /auth/*
│   ├── cameras.py       # /cameras/*
│   ├── incidents.py     # /incidents/*
│   ├── ai.py            # /ai/report
│   └── websocket.py     # /ws/alerts
├── services/
│   ├── incident.py      # Business logic
│   └── notification.py  # Mock emergency dispatch
├── websocket/
│   └── manager.py       # ConnectionManager
└── utils/
    └── seed.py          # Admin seeder
alembic/                 # DB migrations
docker-compose.yml
Dockerfile
requirements.txt
```

## Running in Development

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Start PostgreSQL
docker-compose up db -d

# Copy and configure .env
cp .env.example .env

# Run migrations
alembic upgrade head

# Start API with hot reload
uvicorn app.main:app --reload --port 8000
```

## Production Notes

1. Set a strong `SECRET_KEY` (≥32 random chars)
2. Change default admin password immediately
3. Enable `X-AI-Module-Key` auth in `/ai/report`
4. Use HTTPS + reverse proxy (nginx/traefik)
5. Replace mock notification service with real CAD integration
6. Add rate limiting (e.g., `slowapi`)
7. Configure centralized logging (Sentry, Datadog, etc.)
8. Set `workers` in uvicorn to `2 * CPU_CORES + 1`
