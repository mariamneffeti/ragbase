# Architecture Decision Record

> Multi-Tenant AI SaaS Platform · Free-tier portfolio build

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

| | Free tier | Production alternative |
|---|---|---|
| **Service** | Next.js on Vercel hobby plan | Vercel Pro (~$20/mo) or AWS Amplify |
| **Limits** | 100GB bandwidth, 6,000 build minutes/mo | Unlimited builds, team collaboration, SLA |
| **When to upgrade** | When you need team access, >100GB bandwidth, or 99.99% SLA |

**Why this choice:**
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

| | Free tier | Production alternative |
|---|---|---|
| **Service** | FastAPI on Render free tier | Render Starter ($7/mo), Railway ($5/mo), AWS ECS |
| **Limits** | Spins down after 15 min idle (~30s cold start) | Always-on, auto-scaling, multi-region |
| **When to upgrade** | The moment you need the service always-on for real users |

**Why this choice:**
FastAPI is the fastest Python web framework, with automatic OpenAPI docs, native async support, and Pydantic type hints that double as request validation. Python is the language of the AI/ML ecosystem — LangChain, sentence-transformers, and every major AI SDK are Python-first. Render's free tier is enough for demos and interviews.

**Key reasons:**
- Automatic `/docs` Swagger UI endpoint — zero extra work
- Native `async/await`: stream LLM responses without blocking other requests
- Pydantic validates request and response shapes at the boundary
- Seamless integration with every Python AI/ML library
- `BackgroundTasks` handles async PDF processing without adding Celery

---

## 3. Auth + Database + Storage — Supabase

**Layer:** Data · Free tier (replaces three separate services)

| | Free tier | Production alternative |
|---|---|---|
| **Service** | Supabase free tier | Supabase Pro ($25/mo) or Auth0 + AWS RDS + S3 |
| **Limits** | 500MB DB, 1GB storage, pauses after 1 week inactive, 50,000 MAUs | Always-on, daily backups, no pause |
| **When to upgrade** | When the project needs to be always-on or exceeds 500MB of data |

**Why this choice:**
Supabase consolidates three services into one: PostgreSQL database, JWT-based auth (with social providers, magic links, and MFA), and S3-compatible file storage. This dramatically reduces complexity for a portfolio project. Row Level Security (RLS) enforces multi-tenancy at the database layer, not the application layer — a significant security advantage.

**Key reasons:**
- PostgreSQL is the world's most advanced open-source relational DB — no vendor lock-in
- RLS policies mean even a buggy application layer can't leak another user's data
- Auth handles JWT issuance, refresh tokens, and social OAuth out of the box
- Storage integrates with the same auth system — file access respects the same RLS policies
- JavaScript and Python SDKs are first-class and well maintained

> **Note on splitting at scale:** At production scale, consider splitting into Auth0 (auth), AWS RDS (database), and S3 (storage) for better individual SLAs and more fine-grained control.

---

## 4. Vector Database — Pinecone

**Layer:** AI Data · Free tier

| | Free tier | Production alternative |
|---|---|---|
| **Service** | Pinecone free tier | Pinecone Serverless (~$0.10/1M reads) or Weaviate Cloud |
| **Limits** | 1 index, 100K vectors, 1536 dimensions | Unlimited indexes, vectors, and namespaces |
| **When to upgrade** | When you exceed ~200-300 chunked PDFs, or need multiple indexes |

**Why this choice:**
A vector database stores document chunks as numerical embeddings and retrieves them by semantic similarity — the core of any RAG pipeline. Pinecone is the most popular managed vector DB, with a well-documented API, Python SDK, and namespaces that allow per-user document isolation.

**Key reasons:**
- Approximate nearest neighbor (ANN) search returns results in milliseconds at any scale
- Namespaces provide multi-tenant isolation — each user's documents in their own namespace
- Metadata filtering scopes retrieval to a specific user or document
- Serverless pricing means you pay only for what you query — no idle cost
- **Free alternative:** `pgvector` extension on Supabase keeps everything in one DB at the cost of some query performance at scale

---

## 5. AI API — Groq (free)

**Layer:** AI · Completely free tier

| | Free tier | Production alternative |
|---|---|---|
| **Service** | Groq Cloud free tier | Groq paid, Claude API, or OpenAI API |
| **Limits** | 30 requests/min, 6,000 requests/day, 500K tokens/day | Higher rate limits, SLA, priority access |
| **When to upgrade** | When you exceed 6,000 requests/day or need a specific model like Claude Opus |

**Why this choice:**
Groq offers a genuinely free API with no credit card required — not a trial, not a $5 credit. It runs open-source models (Llama 3, Mixtral, Gemma) at extremely fast inference speeds, often faster than OpenAI. The API is OpenAI-compatible, meaning migration requires changing roughly 3 lines of code. For a portfolio project, 6,000 requests/day is more than enough.

**Key reasons:**
- Completely free — $0/mo, no billing setup required
- OpenAI-compatible SDK: swap the base URL and model name, nothing else changes
- Llama 3.1 70B is competitive with GPT-4o-mini for document Q&A tasks
- Extremely fast inference (Groq's custom LPU hardware) — better UX than many paid APIs
- Get your free API key at [console.groq.com](https://console.groq.com)

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

| | Free tier | Production alternative |
|---|---|---|
| **Service** | FastAPI `BackgroundTasks` + Upstash Redis | Celery + Redis on AWS ElastiCache, or AWS SQS |
| **Limits** | No retry logic, no job dashboard, shares memory with web server | Retries, visibility, horizontal scaling |
| **When to upgrade** | When you need retries on failure, a queue dashboard, or separate worker scaling |

**Why this choice:**
PDF processing — reading, chunking, embedding, storing — is too slow for a synchronous HTTP request. FastAPI's `BackgroundTasks` runs jobs after returning a response, with no extra service to deploy. Upstash provides serverless Redis for tracking job state with a generous free tier.

**Key reasons:**
- Returns `202 Accepted` immediately; client polls for status
- Job state (pending / processing / done / failed) stored in Supabase
- Upstash Redis persists state between requests, unlike in-memory tracking
- No Celery, no separate worker Dockerfile, no extra service to configure
- The Celery upgrade path is well documented when complexity demands it

---

## 7. Deployment — Docker + Vercel + Render

**Layer:** Infrastructure · Free tier

| | Free tier | Production alternative |
|---|---|---|
| **Frontend** | Vercel hobby (free forever) | Vercel Pro ($20/mo) or AWS CloudFront + S3 |
| **Backend** | Render free tier | Render Starter ($7/mo), AWS ECS, or GCP Cloud Run |
| **When to upgrade** | When cold starts are unacceptable, or you need auto-scaling and multi-region |

**Why this choice:**
Docker containers ensure the backend runs identically locally and in production. Vercel handles frontend CDN and HTTPS with zero configuration. Render builds your Dockerfile directly and runs it — the free tier's only downside is a ~30 second cold start after 15 minutes of inactivity, which is acceptable for demos and interviews.

**Key reasons:**
- `docker-compose.yml` runs the full stack locally with one command
- Dockerfile ensures reproducible builds — eliminates environment mismatch issues
- Render reads Dockerfiles directly — no platform-specific configuration
- Environment variables managed through Render and Vercel dashboards, never in code
- GitHub Actions auto-deploys on push to `main` — free CI/CD for portfolio projects

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

---
