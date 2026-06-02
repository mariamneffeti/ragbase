# Problems with the current architecture :

## 1- Cryptographic JWT Verification on FastAPI :

The Next.js  app extracts the user_id from the token and sends it as a raw string or json body to fastapi which creates IDOR(Insecure Direct Object Reference).

- Solution :
fastapi must never trust a raw user ID passed from the frontend. Next.js must forward the raw superbase JWT in the Authorization: Bearer <JWT> header. FastAPI must use a dependency injection guard to fetch Supabase's public keys (/.well-known/jwks.json) and cryptographically decode the token to extract the user's identity securely.

## 2- Implement Tenant Rate Limiting :

Groq free tier limits me to 6000 requests per day.

- Solution :
I need application-level rate limiting enforced inside Fastapi after the JWT is validated.
Implementing a strict quota  to protect my upstream LLM keys from being completely drained.

## 3- Pinecone namespace leak :

if user_id is None or "", Pinecone silently searches the global namespace,mixing all tenants's data.

- Solution :
The fix is a thin wrapper around every Pinecone call that raises a hard exception for any invalid or empty namespace string.

## 4- PDF sandbox escape :

PDF parsers have a history of memory exploits and decompression bombs. 

- Solution:
Three mitigations working together: verify the file's magic bytes (not the extension) in FastAPI, enforce a hard 5 MB limit before parsing begins, and run the FastAPI process as a non-root user inside Docker.


## 5- Background task drops :

Render can kill your container mid-PDF-processing after 15 minutes of idle.

- Solution:
The fix is a reconciliation endpoint that Next.js calls on login: any document stuck in processing for more than 10 minutes gets marked failed, keeping Supabase and Pinecone consistent without needing a paid always-on service
---
