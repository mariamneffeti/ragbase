# Architecture Decision Record

**Multi-Tenant AI SaaS Platform** — Technology decisions, constraints, and scaling guidance

---

## Table of Contents

1. [Overview](#overview)
2. [Frontend — Next.js](#frontend--nextjs)
3. [Backend — FastAPI](#backend--fastapi)
4. [Auth & Storage — Supabase](#auth--storage--supabase)
5. [AI & Embeddings — Groq + Pinecone](#ai--embeddings--groq--pinecone)
6. [Async & Queueing — FastAPI + Upstash](#async--queueing--fastapi--upstash)
7. [Deployment](#deployment)
8. [Data Flow](#data-flow)
9. [Security Architecture](#security-architecture)
10. [Scaling & Cost](#scaling--cost)

---

## Overview

This architecture balances **zero operational overhead** (free tier) with **production readiness**. Every component is independently scalable and containerized.

```
┌─────────────────┐
│  Next.js (Vercel)  │───── JWT ────┐
└─────────────────┘              │
                                  ↓
                          ┌──────────────────┐
                          │ FastAPI (Render) │
                          │  + Rate Limiter  │
                          └──────────────────┘
                                  │
                ┌─────────────────┼─────────────────┐
                ↓                 ↓                 ↓
        ┌─────────────┐   ┌──────────────┐   ┌─────────┐
        │  Supabase   │   │   Pinecone   │   │  Groq   │
        │   (Auth)    │   │   (Vectors)  │   │  (LLM)  │
        └─────────────┘   └──────────────┘   └─────────┘
```

---

## Frontend — Next.js

**Why Next.js?** App Router provides file-based routing, server components, and seamless API integration without a separate backend.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Framework | Next.js 14+ App Router | Modern, React 18 concurrent features |
| Styling | Tailwind CSS | Utility-first, tree-shakeable, small bundle |
| UI Components | Shadcn/ui | Headless, fully customizable, zero lock-in |
| Type Safety | TypeScript | Catch errors at compile time |
| Deployment | Vercel | Zero-config, edge functions, image optimization |

**Key Files:**
- `middleware.ts` — Protects `/dashboard` and `/chat` by verifying Supabase session
- `app/auth/login` — Magic link entry point
- `app/chat/page.tsx` — Streaming RAG interface
- `lib/supabase/client.ts` — Browser-side auth & storage
- `lib/supabase/server.ts` — Server actions for secure operations

**Free Tier Limits:**
- 100GB bandwidth/month
- 6,000 build minutes/month
- No team seats

**When to Upgrade:**
- Bandwidth >100GB/month → Vercel Pro ($20/mo)
- Team collaboration needed → Vercel Pro or Netlify

---

## Backend — FastAPI

**Why FastAPI?** Async-native, automatic OpenAPI docs, native Pydantic validation, 10x faster than Django.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Framework | FastAPI | Native async, auto-docs, Pydantic validation |
| Language | Python | Best-in-class AI/ML ecosystem |
| Async Runtime | Uvicorn + asyncio | Non-blocking I/O for streaming responses |
| Deployment | Render (Docker) | Free tier with 15min auto-spindown |
| Process Model | Single worker | Simple, sufficient for free tier load |

**Key Files:**
- `main.py` — Server initialization, middleware setup
- `api/v1/chat.py` — Streaming chat endpoint (POST /api/v1/chat)
- `api/v1/documents.py` — Upload endpoint (POST /api/v1/documents)
- `api/dependencies/auth.py` — JWKS verification, token validation
- `core/rate_limiter.py` — Per-user quota enforcement
- `services/llm.py` — Groq SDK wrapper with streaming
- `services/vector_store.py` — Pinecone wrapper with namespace validation
- `tasks/ingestion.py` — Async PDF → chunks → embeddings
- `tasks/reconciliation.py` — Recover stuck document processing

**Free Tier Limits:**
- Spins down after 15min idle (~30s cold start)
- 0.5 CPU, 512MB RAM
- 1 free instance per service

**When to Upgrade:**
- Always-on requirement → Render Starter ($7/mo) or Railway ($5/mo)
- Horizontal scaling → AWS ECS or Kubernetes

---

## Auth & Storage — Supabase

**Why Supabase?** Managed PostgreSQL + JWT auth + S3-compatible storage. One vendor replaces three.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Database | PostgreSQL | Mature, ACID, native JSON, Row Level Security |
| Auth | GoTrue (JWT) | Passwordless magic links, OAuth ready |
| Storage | S3-compatible | CDN-backed, RLS-protected objects |
| SDKs | JS & Python | First-class support, no extra dependencies |

**Key Architecture:**

```sql
-- Users table (managed by Supabase Auth)
CREATE TABLE public.users (
  id uuid PRIMARY KEY REFERENCES auth.users(id),
  email TEXT UNIQUE NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

-- Documents table with RLS
CREATE TABLE public.documents (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES users(id),
  filename TEXT NOT NULL,
  file_size INTEGER,
  status TEXT CHECK (status IN ('uploading', 'processing', 'ready', 'failed')),
  created_at TIMESTAMP DEFAULT NOW()
);

-- Row Level Security: Users see only their documents
ALTER TABLE public.documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users see own documents" ON public.documents
  FOR SELECT USING (auth.uid() = user_id);
```

**Security Model:**
- Frontend authenticates with magic link, gets JWT
- JWT forwarded in `Authorization: Bearer <token>` header
- Backend validates JWT signature against Supabase JWKS endpoint
- Supabase RLS policies enforce data isolation at storage layer

**Free Tier Limits:**
- 500MB database storage
- 1GB file storage
- 50,000 MAU
- Pauses after 1 week inactivity

**When to Upgrade:**
- Database >500MB → Supabase Pro ($25/mo)
- Always-on requirement → Supabase Pro (no pause)
- Splitting at scale: Auth0 + AWS RDS + S3 (better SLAs)

---

## AI & Embeddings — Groq + Pinecone

### Groq (LLM)

**Why Groq?** Free tier allows 6,000 requests/day. Fastest open-model inference (LPU hardware).

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Provider | Groq | Free tier, fast inference, modern models |
| Models | Mixtral 8x7B, Llama 2 70B | Open-weight, capable, streaming support |
| Rate Limit | 6k req/day free | Enforced app-side via Upstash Redis |

**When to Upgrade:**
- >6k requests/day → Groq Pro ($5-50/mo) or OpenAI API ($0.001-0.03 per 1K tokens)
- Production: Use OpenAI, Anthropic, or self-hosted Ollama

### Pinecone (Vector DB)

**Why Pinecone?** Managed vector search with 100K vectors free, multi-tenancy via namespaces.

| Aspect | Decision | Rationale |
|--------|----------|-----------|
| Service | Pinecone Serverless | No infra, automatic scaling |
| Index Size | 1 index, 100K vectors | Sufficient for ~200-300 PDFs |
| Namespacing | Per user_id | Multi-tenant data isolation |
| Embeddings | OpenAI text-embedding-3-small (3rd party) | 1536 dims, fast, cheap (~$0.02 per 1M) |

**Namespace Safety:**
```python
# CRITICAL: Vector store wrapper validates namespace
def search_vectors(query_embedding, namespace):
    if not namespace or namespace == "":
        raise ValueError("Namespace cannot be empty (tenant leak)")
    return pinecone_index.query(query_embedding, namespace=namespace)
```

**When to Upgrade:**
- >100K vectors (~300 PDFs) → Pinecone Starter ($0.10 per 1M reads)
- Self-host: Weaviate, Milvus, or pgvector (PostgreSQL)

---

## Async & Queueing — FastAPI + Upstash

**Why not Celery?** FastAPI background tasks are simpler for free tier. Upstash provides serverless Redis.

| Component | Decision | Rationale |
|-----------|----------|-----------|
| Queue | FastAPI background tasks | No external worker, simpler |
| Persistence | Upstash Redis | Serverless, auto-scaling, free tier |
| Rate Limiting | Redis Lua scripts | Sliding window algorithm |

**Architecture:**

```python
# Request → FastAPI (validates JWT) → Upstash (stores quota) → Groq (streams response)

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/api/v1/chat")
@limiter.limit("5/minute")
async def chat(request: ChatRequest, user = Depends(verify_jwt)):
    # Rate check happens here (Upstash Redis Lua script)
    # If allowed, stream response from Groq
    # If exceeded, return 429 Too Many Requests
```

**Handling Cold Starts & Timeouts:**
- Render spins down after 15min idle (~30s cold start)
- PDF processing can exceed 30s timeout
- Solution: `reconciliation.py` endpoint that Next.js calls on login to detect stuck documents

```python
# tasks/reconciliation.py
async def reconcile_documents(user_id: str):
    stuck = await db.documents.find({
        "user_id": user_id,
        "status": "processing",
        "updated_at": {"$lt": datetime.now() - timedelta(minutes=10)}
    })
    for doc in stuck:
        # Mark as failed, clean up Pinecone namespace
        await doc.mark_failed()
        await pinecone.delete(namespace=user_id, ids=[doc.id])
```

---

## Deployment

### Frontend → Vercel

```bash
# 1. Connect GitHub repo
# 2. Vercel auto-detects Next.js
# 3. Set environment variables in Vercel dashboard:
#    NEXT_PUBLIC_SUPABASE_URL=https://xxx.supabase.co
#    NEXT_PUBLIC_SUPABASE_ANON_KEY=eyJxxx
#    NEXT_PUBLIC_API_URL=https://api.yourdomain.com
# 4. Deploy: git push → Vercel auto-deploys
```

### Backend → Render

```bash
# 1. Push backend/ to GitHub root or create monorepo
# 2. Connect GitHub to Render
# 3. Create Web Service:
#    - Runtime: Docker
#    - Root Directory: backend
#    - Build Command: docker build -t app .
# 4. Set environment variables:
#    - SUPABASE_URL, SUPABASE_SERVICE_KEY
#    - PINECONE_API_KEY, GROQ_API_KEY
#    - UPSTASH_REDIS_URL
#    - DATABASE_URL (Supabase PostgreSQL)
# 5. Deploy: git push → Render builds & deploys Docker image
```

### Local Development

```bash
# Start PostgreSQL + Redis
docker-compose up -d

# Backend
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload

# Frontend (new terminal)
cd frontend
npm install
npm run dev
```

---

## Data Flow

### 1. User Authentication

```
User → Magic Link (Supabase) → JWT Token → Frontend stores token
Frontend → Every request includes JWT in Authorization header
FastAPI → Verifies JWT signature against Supabase JWKS endpoint
```

### 2. Document Upload & Processing

```
User → Upload PDF (frontend) → Multipart to /api/v1/documents
FastAPI → Validate magic bytes & file size
FastAPI → Save to Supabase Storage → Mark document as "processing"
FastAPI → Background task: PDF → chunks → embeddings
Background → Pinecone (namespace=user_id) + Supabase (status="ready")
User → Next login: reconciliation endpoint detects stuck documents
```

### 3. Chat Request

```
User → Message + selected doc_id (frontend) → /api/v1/chat
FastAPI → Verify JWT (extract user_id)
FastAPI → Rate limit check (Upstash Redis)
FastAPI → Retrieve chat history (Supabase)
FastAPI → Vector search (Pinecone namespace=user_id, doc_id filter)
FastAPI → Groq LLM (system prompt + context + message)
FastAPI → Stream response back to frontend
Frontend → Display streamed tokens in real-time
```

---

## Security Architecture

### 1. JWT Verification (JWKS)

**Problem:** Frontend must not pass raw user_id; trusting it creates IDOR.

**Solution:**
```python
# FastAPI dependency
from fastapi import Depends, HTTPException
from jose import JWTError, jwt
import requests

JWKS_URL = f"{SUPABASE_URL}/.well-known/jwks.json"

async def verify_jwt(token: str = Depends(HTTPBearer())) -> str:
    try:
        jwks = requests.get(JWKS_URL).json()
        payload = jwt.decode(token.credentials, options={"verify_signature": False})
        # Verify signature against JWKS
        return payload["sub"]  # user_id
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")
```

### 2. Namespace Validation (Pinecone)

**Problem:** Empty namespace leaks all tenant data.

**Solution:**
```python
# services/vector_store.py
def search(query_embedding, user_id):
    if not user_id or user_id == "":
        raise ValueError("Namespace cannot be empty")
    return pinecone_index.query(query_embedding, namespace=user_id)
```

### 3. File Upload Validation

**Problem:** Malicious PDFs exploit parser vulnerabilities.

**Solution:**
```python
# utils/file_validator.py
import magic

def validate_upload(file_bytes):
    # Check magic bytes (not extension)
    mime_type = magic.from_buffer(file_bytes, mime=True)
    if mime_type not in ["application/pdf", "text/plain"]:
        raise ValueError("Only PDF and TXT allowed")
    
    # Enforce size limit
    if len(file_bytes) > 5 * 1024 * 1024:  # 5 MB
        raise ValueError("File exceeds 5 MB limit")
    
    return True
```

### 4. Container Hardening

**Dockerfile:**
```dockerfile
FROM python:3.11-slim

# Create non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app
COPY --chown=appuser:appuser . .
RUN pip install -r requirements.txt

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

## Scaling & Cost

### Current Costs (Free Tier)

| Service | Cost | Limits |
|---------|------|--------|
| Vercel | $0 | 100GB bandwidth, 6k build min/mo |
| Render | $0 | 15min spindown, 0.5 CPU, 512MB RAM |
| Supabase | $0 | 500MB DB, 1GB storage, 50k MAU |
| Pinecone | $0 | 100k vectors, 1 index |
| Groq | $0 | 6k requests/day |
| Upstash | $0 (pay-per-use) | First 10k requests free/day |
| **Total** | **~$0** | Suitable for portfolio projects |

### Upgrade Path (Production)

| Phase | Frontend | Backend | Auth/DB | Vector | LLM | Cost |
|-------|----------|---------|---------|--------|-----|------|
| **Free** | Vercel Free | Render Free | Supabase Free | Pinecone Free | Groq Free | $0 |
| **Hobbyist** | Vercel Free | Render Starter $7 | Supabase Pro $25 | Pinecone $0.10/1M | Groq Pro $5 | ~$40/mo |
| **Startup** | Vercel Pro $20 | Railway $5-50 | AWS RDS $50 + Auth0 $0 | Weaviate Cloud $0-500 | OpenAI $0.10/1K | $100-500/mo |
| **Production** | Vercel Pro $20 | ECS Auto-Scaling | Multi-region RDS | Self-hosted GPU | LLMOps Platform | $1000+/mo |

### Migration Path

**Free → Hobbyist:**
1. Keep Vercel, upgrade Render to Starter (remove spindown)
2. Upgrade Supabase Pro (no pause, daily backups)
3. Switch to OpenAI API (more reliable than Groq)
4. Keep Pinecone free until 300+ PDFs

**Hobbyist → Startup:**
1. Backend: Railway or AWS Elastic Beanstalk (multi-instance)
2. Database: AWS RDS (better SLA, automated failover)
3. Vector: Self-host pgvector (on RDS) or Milvus
4. LLM: OpenAI or Anthropic (pay-per-request model)
5. Monitoring: DataDog or New Relic

---

## Decision Log

| Decision | Rationale | Alternative Considered |
|----------|-----------|------------------------|
| Next.js over Flask | App Router, edge functions, streaming | Svelte, Vue, plain React |
| FastAPI over Django | Async-native, auto-docs, speed | Django REST, Starlette, Quart |
| Supabase over Auth0+RDS+S3 | Integrated, free tier generous, RLS built-in | Firebase, AWS Cognito+RDS+S3 |
| Groq over OpenAI | Free tier, fast inference, community models | OpenAI, Anthropic, Replicate |
| Pinecone over pgvector | Managed, multi-tenant namespaces, free vectors | pgvector, Weaviate, Milvus |
| Upstash over Redis Cloud | Serverless pricing, free tier, HTTP API | Redis Cloud, Valkey, in-memory |

---

## References

- [Next.js 14 Documentation](https://nextjs.org/docs)
- [FastAPI User Guide](https://fastapi.tiangolo.com)
- [Supabase Auth & RLS](https://supabase.com/docs)
- [Pinecone Namespaces](https://docs.pinecone.io/guides/indexes/namespaces)
- [Groq API Reference](https://console.groq.com/docs)
- [Render Deployment Guide](https://render.com/docs)

### Why this choice

A vector database stores chunked document matrices as high-dimensional semantic vectors to execute similarity searches. Pinecone provides a fully managed infrastructure that scales sub-second nearest-neighbor matching alongside structured metadata filtering parameters.

**Key reasons:**
- Approximate Nearest Neighbor (ANN) indexes return query sets within millisecond tolerances
- Programmatic document namespaces explicitly separate indexing groups on a per-tenant basis
- Implements a dedicated vector service wrapper layer that programmatically validates the target namespace against the authenticated tenant ID before executing operations
- Serverless indexing maps resource billing strictly to query activity rather than idle uptime

> **Free alternative:** The `pgvector` extension inside Supabase offers single-database consolidation when deployment consolidation is prioritized over standalone vector search performance.

---

## 5. AI API — Groq (free)

**Layer:** AI · Completely free tier

| | Free Tier | Production Alternative |
|---|---|---|
| **Service** | Groq Cloud free tier | Groq paid, Claude API, or OpenAI API |
| **Limits** | 30 requests/min, 6,000 requests/day, 500K tokens/day | Higher rate limits, SLA, priority access |
| **When to upgrade** | When you exceed 6,000 requests/day or need a specific model like Claude Opus | |

### Why this choice

Groq provides a robust free tier with access to open-weights architectures (Llama, Mixtral) running on specialized LPU (Language Processing Unit) hardware. The interface exposed by the SDK matches standard inference protocol conventions, reducing systemic engine-switching overhead.

**Key reasons:**
- Fully accessible inference pricing with zero upfront usage requirements
- Interface schema compliance allowing models to be updated or swapped with minimal backend configuration alterations
- High token-per-second processing velocity suited for responsive document context analysis
- Built-in tool calling support enables straightforward systemic grounding within text generation pipelines

**Migration from Claude/OpenAI is 3 lines:**

```python
# Before (OpenAI)
from openai import OpenAI
client = OpenAI(api_key="sk-...")

# After (Groq — drop-in replacement)
from groq import Groq
client = Groq(api_key="gsk_...")  # free at console.groq.com
# Everything else stays identical
```

> **Recommended model:** `llama-3.1-70b-versatile` for best quality, or `llama-3.1-8b-instant` for fastest responses.

---

## 6. Queue & Async Processing — FastAPI Background Tasks + Upstash Redis

**Layer:** Processing · Free tier

| | Free Tier | Production Alternative |
|---|---|---|
| **Service** | FastAPI BackgroundTasks + Upstash Redis | Celery + Redis on AWS ElastiCache, or AWS SQS |
| **Limits** | No retry logic, no job dashboard, shares memory with web server | Retries, visibility, horizontal scaling |
| **When to upgrade** | When you need retries on failure, a queue dashboard, or separate worker scaling | |

### Why this choice

Document text extraction, recursive chunk generation, and embedding calculations are executed asynchronously outside the standard request-response loop. FastAPI's worker-integrated thread runner processes multi-stage ingestion flows non-blockingly, while a cloud Redis instance acts as the centralized transaction state store.

**Key reasons:**
- Endpoints emit instantaneous `202 Accepted` acknowledgments, offloading heavy processing tasks
- Tracks multi-state pipelines (e.g., `pending`, `parsing`, `embedded`, `failed`) via database mappings
- Integrates binary magic-byte content validation and a 5MB size restriction gate prior to document ingestion
- Uses serverless Upstash Redis instances to preserve system state values independent of local container memory configurations
- Employs an asynchronous state pipeline where a lazy reconciliation mechanism executes upon dashboard load to sync and recover interrupted ingestion operations

---

## 7. Deployment — Docker + Vercel + Render

**Layer:** Infrastructure · Free tier

| | Free Tier | Production Alternative |
|---|---|---|
| **Frontend** | Vercel hobby (free forever) | Vercel Pro ($20/mo) or AWS CloudFront + S3 |
| **Backend** | Render free tier | Render Starter ($7/mo), AWS ECS, or GCP Cloud Run |
| **When to upgrade** | When cold starts are unacceptable, or you need auto-scaling and multi-region | |

### Why this choice

Containerizing the backend code creates predictable runtime footprints across local deployment systems and live staging hosts. Vercel acts as the automated CDN border layer for static delivery, while Render reads container configuration patterns directly to host the web app engine.

**Key reasons:**
- Unified `docker-compose.yml` multi-container setups spin up consistent local development versions instantly
- Custom backend Dockerfiles implement dedicated non-root Linux user profiles (`USER appuser`) to isolate host system permissions
- Automated Git-integrated triggers streamline continuous integration paths from standard branch structures
- Environment strings are bound at the runtime container configuration panel layer rather than being hardcoded into repository check-ins

---

## Monthly Cost Summary

| Service | Free Tier | Production Estimate |
|---|---|---|
| Vercel (frontend) | $0 forever | ~$20/mo (Pro) |
| Render (backend) | $0 (cold starts) | ~$7/mo (Starter) |
| Supabase (auth + DB + storage) | $0 (pauses on inactivity) | ~$25/mo (Pro) |
| Pinecone (vector DB) | $0 (100K vectors) | ~$10–30/mo (serverless) |
| Groq AI API | $0 (6,000 req/day) | Scales with usage |
| Upstash Redis | $0 (10K cmds/day) | ~$10/mo (pay-as-you-go) |
| **Total** | **$0/mo** | **~$70–90/mo** |

> All free tiers are subject to each provider's terms and may change. Verify current limits before relying on them for production workloads.