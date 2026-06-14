import Link from "next/link";

export default function LandingPage() {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-bg px-6">
      <div className="max-w-xl w-full">
        {/* Eyebrow */}
        <p className="font-mono text-xs tracking-widest text-accent uppercase mb-6">
          Document Intelligence
        </p>

        <h1 className="text-5xl font-semibold text-text leading-[1.1] tracking-tight mb-5">
          Enterprise RAG<br />Platform
        </h1>

        <p className="text-text-2 text-base leading-relaxed mb-10 max-w-sm">
          Secure, multi-tenant document intelligence. Upload, index, and query
          your knowledge base with AI.
        </p>

        <div className="flex items-center gap-3">
          <Link
            href="/dashboard"
            className="inline-flex items-center px-5 py-2.5 bg-accent text-white text-sm font-medium rounded-md hover:bg-accent-2 transition-colors duration-150"
          >
            Get started
          </Link>
          <Link
            href="/auth/login"
            className="inline-flex items-center px-5 py-2.5 bg-surface border border-border text-text text-sm font-medium rounded-md hover:bg-surface-2 transition-colors duration-150"
          >
            Sign in
          </Link>
        </div>
      </div>

      {/* Subtle bottom rule */}
      <div className="absolute bottom-8 left-0 right-0 flex justify-center">
        <p className="font-mono text-xs text-text-2 opacity-50">
          Powered by Pinecone · Groq · Supabase
        </p>
      </div>
    </main>
  );
}