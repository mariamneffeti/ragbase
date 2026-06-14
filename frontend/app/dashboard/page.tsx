"use client";

import { useState } from "react";
import FileUpload from "@/components/file-upload";
import DocumentList from "@/components/document-list";

export default function DashboardPage() {
  const [refreshKey, setRefreshKey] = useState(0);

  return (
    <div className="max-w-4xl mx-auto">
      <h2 className="text-3xl font-bold mb-6">Documents</h2>
      <FileUpload onSuccess={() => setRefreshKey((k) => k + 1)} />
      <DocumentList key={refreshKey} />
    </div>
  );
}