"use client";

import { useEffect, useState } from "react";
import { useSupabase } from "@/components/providers";
import { toast } from "sonner";

interface Document {
  document_id: string;
  title: string;
  chunk_count: number;
}

export default function DocumentList() {
  const { supabase, user } = useSupabase();
  const [docs, setDocs] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const tenantId = user?.app_metadata?.tenant_id || "default-tenant";

  const fetchDocs = async () => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/documents/list`,
        { headers: { "X-Tenant-ID": tenantId, "Authorization": `Bearer ${session?.access_token}` } }
      );
      if (!res.ok) throw new Error("Failed to fetch documents");
      const data = await res.json();
      setDocs(data);
    } catch (err) {
      toast.error("Could not load documents");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocs();
  }, [tenantId]);

  const deleteDocument = async (docId: string) => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      const res = await fetch(
        `${process.env.NEXT_PUBLIC_API_URL}/documents/${docId}`,
        {
          method: "DELETE",
          headers: { "X-Tenant-ID": tenantId, "Authorization": `Bearer ${session?.access_token}` },
        }
      );
      if (!res.ok) throw new Error("Delete failed");
      toast.success("Document deleted");
      setDocs(docs.filter((d) => d.document_id !== docId));
    } catch (err) {
      toast.error("Delete failed");
    }
  };

  if (loading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <div key={i} className="h-14 bg-surface-2 rounded-lg animate-pulse" />
        ))}
      </div>
    );
  }

  if (docs.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center py-16 border border-dashed border-border rounded-lg">
        <svg className="w-8 h-8 text-text-2 mb-3" fill="none" stroke="currentColor" strokeWidth={1.25} viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 0 0-3.375-3.375h-1.5A1.125 1.125 0 0 1 13.5 7.125v-1.5a3.375 3.375 0 0 0-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 0 0-9-9Z" />
        </svg>
        <p className="text-sm text-text-2">No documents yet. Upload one to get started.</p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {docs.map((doc) => (
        <div
          key={doc.document_id}
          className="flex items-center justify-between bg-surface border border-border rounded-lg px-4 py-3 group hover:border-accent/40 transition-colors duration-100"
        >
          <div className="min-w-0">
            <p className="text-sm font-medium text-text truncate">{doc.title}</p>
            <p className="font-mono text-xs text-text-2 mt-0.5">{doc.chunk_count} chunks</p>
          </div>
          <button
            onClick={() => deleteDocument(doc.document_id)}
            className="ml-4 text-xs text-text-2 hover:text-danger opacity-0 group-hover:opacity-100 transition-all duration-100 shrink-0"
          >
            Delete
          </button>
        </div>
      ))}
    </div>
  );
}