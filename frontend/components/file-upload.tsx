"use client";

import { useCallback, useState } from "react";
import { useSupabase } from "@/components/providers";
import { toast } from "sonner";

export default function FileUpload({ onSuccess }: { onSuccess?: () => void }) {
  const { user } = useSupabase();
  const tenantId = user?.app_metadata?.tenant_id || "default-tenant";
  const [uploading, setUploading] = useState(false);

  const onFileChange = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      setUploading(true);
      const formData = new FormData();
      formData.append("file", file);

      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL}/documents/upload`,
          {
            method: "POST",
            headers: { "X-Tenant-ID": tenantId },
            body: formData,
          }
        );
        if (!res.ok) {
          const errorData = await res.json();
          throw new Error(errorData.detail || "Upload failed");
        }
        toast.success("File uploaded successfully!");
        onSuccess?.();
      } catch (err: any) {
        toast.error(err.message);
      } finally {
        setUploading(false);
        e.target.value = "";
      }
    },
    [tenantId, onSuccess]
  );

  return (
    <div className="mb-6">
      <label
        className={`group flex flex-col items-center justify-center w-full border border-dashed border-border rounded-lg px-6 py-8 cursor-pointer transition-colors duration-150 ${
          uploading ? "opacity-50 cursor-not-allowed" : "hover:border-accent hover:bg-surface"
        }`}
      >
        <svg
          className="w-8 h-8 text-text-2 mb-3 group-hover:text-accent transition-colors"
          fill="none"
          stroke="currentColor"
          strokeWidth={1.25}
          viewBox="0 0 24 24"
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 0 0 5.25 21h13.5A2.25 2.25 0 0 0 21 18.75V16.5m-13.5-9L12 3m0 0 4.5 4.5M12 3v13.5" />
        </svg>
        <span className="text-sm font-medium text-text mb-1">
          {uploading ? "Uploading…" : "Click to upload a file"}
        </span>
        <span className="text-xs text-text-2">
          PDF, DOCX, CSV, MD, or TXT — max 10 MB
        </span>
        <input
          type="file"
          onChange={onFileChange}
          disabled={uploading}
          className="sr-only"
        />
      </label>
    </div>
  );
}