## Project Structure
```
my-saas/
├── frontend/               # Next.js — deploy to Vercel
│   ├── app/
│   │   ├── page.tsx        # landing page
│   │   ├── dashboard/      # after login
│   │   └── chat/           # chat interface
│   ├── components/
│   └── .env.local
│
├── backend/                # FastAPI — deploy to Render
│   ├── main.py             # app entry point
│   ├── api/
│   │   ├── auth.py         # login/signup routes
│   │   ├── documents.py    # upload + process
│   │   └── chat.py         # RAG + streaming
│   ├── rag/
│   │   ├── chunker.py      # split PDF into chunks
│   │   ├── embedder.py     # call embedding model
│   │   └── retriever.py    # query Pinecone
│   ├── db/
│   │   └── supabase.py     # DB + auth client
│   ├── tasks.py            # background jobs
│   └── .env
│
├── docker-compose.yml      # local dev only
└── README.md               # architecture diagram goes here```