"use client";

import { useSupabase } from "@/components/providers";

export default function SignOutButton() {
  const { supabase } = useSupabase();

  return (
    <button
      onClick={() => supabase?.auth.signOut()}
      className="w-full text-left hover:bg-gray-700 p-2 rounded text-red-300"
    >
      Sign Out
    </button>
  );
}