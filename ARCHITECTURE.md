# Architecture Decision Record
**Multi-Tenant AI SaaS Platform · Free-tier portfolio build**

This document explains every architectural decision in this project — why each tool was chosen, what the free-tier constraints are, and what the production alternative looks like when it's time to scale.

---

## Table of Contents

1. [Frontend — Next.js + React + Tailwind](#1-frontend--nextjs--react--tailwind)
2. [Backend — FastAPI](#2-backend--fastapi)
3. [Auth + Database + Storage — Supabase](#3-auth--database--storage--supabase)
4. [Vector Database — Pinecone](#4-vector-database--pinecone)
5. [AI API — Groq (free)](#5-ai-api--groq-free)
6. [Queue & Async Processing — FastAPI Background Tasks + Upstash Redis](#6-queue--async-processing--fastapi-background-tasks--upstash-redis)
7. [Deployment — Docker + Vercel + Render](#7-deployment--docker--vercel--render)
8. [Monthly Cost Summary](#monthly-cost-summary)

---

## 1. Frontend — Next.js + React + Tailwind

**Layer:** Frontend · Deployed on Vercel (free tier)

| | Free Tier | Production Alternative |
|---|---|---|
| **Service** | Next.js on Vercel hobby plan | Vercel Pro (~$20/mo) or AWS Amplify |
| **Limits** | 100GB bandwidth, 6,000 build minutes/mo | Unlimited builds, team collaboration, SLA |
| **When to upgrade** | When you need team access, >100GB bandwidth, or 99.99% SLA | |

### Why this choice

Next.js combines React with server-side rendering, API routes, and file-based routing in one framework. Vercel — built by the Next.js team — offers zero-config deployment with a global CDN, preview URLs for every branch, and automatic HTTPS. The free tier is generous enough to run a portfolio project indefinitely.

**Key reasons:**
- File-based routing eliminates manual router configuration
- API routes let you add lightweight backend logic without a separate server
- Tailwind utility classes map directly to design decisions — no custom CSS files
- Vercel preview deployments make sharing work-in-progress trivial
- Massive React ecosystem: a library exists for every UI problem

---

## 2. Backend — FastAPI

**Layer:** Backend API · Deployed on Render (free tier)

| | Free Tier | Production Alternative |
|---|---|---|
| **Service** | FastAPI on Render free tier | Render Starter ($7/mo), Railway ($5/mo), AWS ECS |
| **Limits** | Spins down after 15 min idle (~30s cold start) | Always-on, auto-scaling, multi-region |
| **When to upgrade** | The moment you need the service always-on for real users | |

### Why this choice

FastAPI is the fastest Python web framework, featuring native async support, automated OpenAPI documentation generation, and structural data validation via Pydantic. Python serves as the foundational language for the AI/ML ecosystem, supporting all major AI SDKs and pipeline utilities natively.

**Key reasons:**
- Automatic `/docs` Swagger UI endpoint for immediate API specification interaction
- Native async/await handling to stream tokenized LLM responses efficiently without blocking concurrent operations
- Formally validates inbound payloads at the application boundaries using Pydantic type hints
- Integrates an internal dependency injection pipeline to cryptographically decode client-forwarded access tokens via Supabase JWKS endpoints
- Leverages `slowapi` connected to an external Redis instance to enforce a per-user endpoint quota (e.g., 5 requests/minute for AI chat routes)

---

## 3. Auth + Database + Storage — Supabase

**Layer:** Data · Free tier (replaces three separate services)

| | Free Tier | Production Alternative |
|---|---|---|
| **Service** | Supabase free tier | Supabase Pro ($25/mo) or Auth0 + AWS RDS + S3 |
| **Limits** | 500MB DB, 1GB storage, pauses after 1 week inactive, 50,000 MAUs | Always-on, daily backups, no pause |
| **When to upgrade** | When the project needs to be always-on or exceeds 500MB of data | |

### Why this choice

Supabase consolidates a PostgreSQL database, a JSON Web Token (JWT) identity provider, and S3-compatible object storage into a single infrastructure footprint. Row Level Security (RLS) policies decouple data ownership, ensuring multi-tenancy rules are consistently evaluated directly within the storage engine.

**Key reasons:**
- PostgreSQL structure provides core relational capabilities with zero proprietary vendor lock-in
- RLS rules restrict direct records visibility based on authenticated claims embedded within the token
- The client UI exchanges login credentials directly with GoTrue endpoints, acquiring stateless access tokens forwarded upstream to the FastAPI layer
- Storage engine access paths are verified using the exact same database-integrated RLS policies
- Maintains native, highly optimized SDK libraries across both JavaScript and Python environments

> **Note on splitting at scale:** At production scale, consider splitting into Auth0 (auth), AWS RDS (database), and S3 (storage) for better individual SLAs and more fine-grained control.

---

## 4. Vector Database — Pinecone

**Layer:** AI Data · Free tier

| | Free Tier | Production Alternative |
|---|---|---|
| **Service** | Pinecone free tier | Pinecone Serverless (~$0.10/1M reads) or Weaviate Cloud |
| **Limits** | 1 index, 100K vectors, 1536 dimensions | Unlimited indexes, vectors, and namespaces |
| **When to upgrade** | When you exceed ~200–300 chunked PDFs, or need multiple indexes | |

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