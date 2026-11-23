"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { apiFetch } from "@/lib/api/client";
import type { Workspace } from "@/lib/api/types";

export default function HomeRedirectPage() {
  const router = useRouter();

  useEffect(() => {
    let cancelled = false;
    async function resolveLanding() {
      try {
        const res = await apiFetch<{ items: Workspace[] }>("/workspaces");
        if (cancelled) return;
        if (res.items.length === 0) {
          router.replace("/onboarding/create-workspace");
          return;
        }
        const saved = window.localStorage.getItem("dc-last-workspace");
        const match = res.items.find((w) => w.id === saved) ?? res.items[0]!;
        router.replace(`/w/${match.id}/overview`);
      } catch {
        if (!cancelled) {
          router.replace("/login");
        }
      }
    }
    resolveLanding();
    return () => {
      cancelled = true;
    };
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--surface))] text-sm text-[hsl(var(--muted-foreground))]">
      Loading workspace...
    </div>
  );
}
