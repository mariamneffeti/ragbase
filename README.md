# AI SaaS Platform

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Visit-green)](https://ragbase-2rlwe8dyg-mariamneffetis-projects.vercel.app)

A production-ready, multi-tenant AI chat application with Retrieval-Augmented Generation (RAG) capabilities. Upload documents, ask questions, and get AI-powered answers grounded in your uploaded files.

**Status:** Free-tier portfolio project · All components containerized & production-deployable

---

## 🚀 Features

- **Authentication:** Magic link login via Supabase (passwordless)
- **Document Management:** Drag-and-drop PDF/TXT upload with async processing
- **RAG Chat:** Stream AI responses grounded in your documents via Groq
- **Rate Limiting:** Per-user request quotas (protected LLM usage)
- **Multi-tenancy:** Row-level security ensures data isolation
- **Secure JWT Verification:** Cryptographic token validation on backend

---

## 📋 Prerequisites

- **Node.js 18+** (frontend)
- **Python 3.11+** (backend)
- **Docker** (optional, for local database)
- **Free accounts:**
  - [Supabase](https://supabase.com) — auth, database, storage
  - [Pinecone](https://pinecone.io) — vector embeddings
  - [Groq](https://console.groq.com) — LLM API (free tier: 6k requests/day)
  - [Upstash](https://upstash.com) — Redis for rate limiting

---

## 🏗️ Project Structure

```
.
├── frontend/                    # Next.js 14+ (Vercel deployment)
│   ├── app/                     # App Router (routes, pages, layouts)
│   ├── components/              # React components (chat, upload, sidebar)
│   ├── lib/                     # Utilities (Supabase clients, helpers)
│   └── middleware.ts            # Auth middleware (route protection)
│
├── backend/                     # FastAPI (Docker → Render)
│   ├── app/
│   │   ├── main.py              # Server entry point
│   │   ├── api/                 # API endpoints (chat, documents)
│   │   ├── core/                # Configuration, rate limiting
│   │   ├── services/            # LLM, vector store logic
│   │   ├── tasks/               # Async jobs (PDF ingestion, reconciliation)
│   │   └── utils/               # Validators, helpers
│   ├── Dockerfile               # Multi-stage build, non-root user
│   └── requirements.txt
│
├── docker-compose.yml           # Local dev: PostgreSQL + Redis
└── docs/                        # This folder
```

---

## 🚦 Quick Start

### 1. Frontend Setup

```bash
cd frontend
npm install
cp .env.local.example .env.local
# Edit .env.local with your Supabase & API URL
npm run dev
```

Runs on `http://localhost:3000`

### 2. Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt

# Start local PostgreSQL + Redis
docker-compose up -d

# Run server
python -m uvicorn app.main:app --reload
```

Runs on `http://localhost:8000` · Docs at `/docs`

### 3. Environment Variables

**Frontend** (`.env.local`):
```
NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJxx...
NEXT_PUBLIC_API_URL=http://localhost:8000
```

**Backend** (`.env`):
```
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_KEY=eyJxx...
PINECONE_API_KEY=xxx
GROQ_API_KEY=xxx
UPSTASH_REDIS_URL=redis://localhost:6379
DATABASE_URL=postgresql://user:password@localhost:5432/saas
```

---

## 🚢 Deployment

### Frontend → Vercel
```bash
cd frontend
vercel deploy
```

### Backend → Render (Docker)
1. Connect GitHub repo to Render
2. Select the `backend/` directory
3. Set environment variables
4. Deploy

---

## 🔒 Security Features

| Feature | Details |
|---------|---------|
| **Auth** | Supabase JWT verified cryptographically (JWKS validation) |
| **Rate Limiting** | Per-user quotas (5 req/min chat) via Upstash Redis |
| **File Validation** | Magic-byte verification (not extension) + 5MB limit |
| **Namespacing** | Pinecone queries scoped to user_id (no data leaks) |
| **Container** | Runs as non-root user, health checks enabled |

---

## 🐛 Common Issues

| Issue | Solution |
|-------|----------|
| **"Invalid API key"** | Check `.env` files, restart server |
| **PDF upload fails** | Verify file <5MB, check backend logs |
| **Rate limit errors** | Wait 60 seconds or upgrade quota in code |
| **Cold start slow** | Normal on free tier (Render spins down after 15min) |

---

## 📚 Documentation

- **[ARCHITECTURE.md](ARCHITECTURE.md)** — Technology decisions, scaling notes
- **[DOCUMENTATION.md](DOCUMENTATION.md)** — API reference, component guide, deployment troubleshooting

---

## 📜 License

MIT
```