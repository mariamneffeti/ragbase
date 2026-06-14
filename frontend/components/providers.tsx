// components/providers.tsx
"use client";

import { createBrowserClient } from "@supabase/ssr";
import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import type { SupabaseClient, User } from "@supabase/supabase-js";
import { Toaster } from "sonner";

interface SupabaseContextType {
  supabase: SupabaseClient;
  user: User | null;
  loading: boolean;
}

const SupabaseContext = createContext<SupabaseContextType | undefined>(undefined);

export function useSupabase() {
  const context = useContext(SupabaseContext);
  if (!context) throw new Error("useSupabase must be used within Providers");
  return context;
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [supabase] = useState(() =>
    createBrowserClient(
      process.env.NEXT_PUBLIC_SUPABASE_URL!,
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
    )
  );
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const router = useRouter();

  useEffect(() => {
    // Get initial session
    supabase.auth.getUser().then(({ data: { user } }) => {
      setUser(user);
      setLoading(false);
    });

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((event, session) => {
      setUser(session?.user ?? null);
      setLoading(false);
      if (event === "SIGNED_OUT") {
        router.push("/auth/login");
      }
    });

    return () => subscription.unsubscribe();
  }, [supabase, router]);

  return (
    <SupabaseContext.Provider value={{ supabase, user, loading }}>
      {children}
      <Toaster richColors position="top-right" />
    </SupabaseContext.Provider>
  );
}