## Project Structure
```
my-saas/
├── frontend/                       # Next.js (Deployed to Vercel)
│   ├── app/
│   │   ├── page.tsx                # Public marketing/landing page
│   │   ├── dashboard/              # Secure dashboard layout & document viewer
│   │   └── chat/                   # UI for streaming conversational RAG
│   ├── middleware.ts               # Protects client routes via HTTP-only session checks
│   ├── components/
│   └── .env.local
│
├── backend/                        # FastAPI (Deployed to Render via Docker)
│   ├── Dockerfile                  # Hardened container footprint running as USER appuser
│   ├── requirements.txt
│   └── app/
│       ├── main.py                 # Application initialization & Redis-backed slowapi mounting
│       │
│       ├── api/
│       │   ├── dependencies/
│       │   │   └── auth.py         # Injected security guard verifying Supabase JWKS tokens
│       │   └── v1/
│       │       ├── chat.py         # Protected endpoint for streaming AI responses
│       │       └── documents.py    # Gateway for validating and managing uploaded files
│       │
│       ├── core/
│       │   ├── config.py           # Strictly typed global environment variables (Pydantic Settings)
│       │   └── rate_limiter.py     # Upstash Redis state configuration for request quotas
│       │
│       ├── services/
│       │   ├── llm.py              # Groq LPU client initialization and response streaming
│       │   └── vector_store.py     # Fail-safe namespace abstraction layer for Pinecone
│       │
│       ├── tasks/
│       │   ├── ingestion.py        # Asynchronous processing (parsing, chunking, embedding)
│       │   └── reconciliation.py   # State tracking recovery checks executed lazily on page load
│       │
│       └── utils/
│           └── file_validator.py   # Content sniffer checking binary magic-bytes & constraints
│
├── docker-compose.yml              # Configures local database and local Redis emulation
└── README.md
```