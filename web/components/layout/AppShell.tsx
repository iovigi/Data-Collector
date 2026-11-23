"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  BarChart3,
  BookOpen,
  Briefcase,
  ChevronLeft,
  ChevronRight,
  Cpu,
  Database,
  FileCode2,
  FolderKanban,
  KeyRound,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Settings,
  ShieldCheck,
  Sun,
  Users,
  Webhook,
  X,
} from "lucide-react";
import { apiAuthPost, apiFetch } from "@/lib/api/client";
import type { MeResponse, Workspace, WorkspaceCapabilities } from "@/lib/api/types";
import { useTheme } from "@/components/providers";

export function AppShell({
  workspaceId,
  children,
}: {
  workspaceId?: string;
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { theme, toggleTheme } = useTheme();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const meQuery = useQuery({
    queryKey: ["me"],
    queryFn: () => apiFetch<MeResponse>("/me"),
  });

  const wsListQuery = useQuery({
    queryKey: ["workspaces"],
    queryFn: () => apiFetch<{ items: Workspace[] }>("/workspaces"),
  });

  const capsQuery = useQuery({
    queryKey: ["capabilities", workspaceId],
    queryFn: () => apiFetch<WorkspaceCapabilities>(`/workspaces/${workspaceId}/capabilities`),
    enabled: Boolean(workspaceId),
  });

  useEffect(() => {
    if (meQuery.isError) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [meQuery.isError, pathname, router]);

  async function handleLogout() {
    await apiAuthPost("/api/auth/logout").catch(() => {});
    queryClient.clear();
    router.replace("/login");
  }

  function handleSwitchWorkspace(nextWid: string) {
    if (!nextWid || nextWid === workspaceId) return;
    queryClient.cancelQueries();
    if (workspaceId) {
      queryClient.removeQueries({
        predicate: (q) => Array.isArray(q.queryKey) && q.queryKey.includes(workspaceId),
      });
    }
    window.localStorage.setItem("dc-last-workspace", nextWid);
    router.push(`/w/${nextWid}/overview`);
  }

  const navItems = workspaceId
    ? [
        { href: `/w/${workspaceId}/overview`, label: "Overview", icon: LayoutDashboard },
        { href: `/w/${workspaceId}/projects`, label: "Projects", icon: FolderKanban },
        { href: `/w/${workspaceId}/collections`, label: "Collections", icon: Database },
        { href: `/w/${workspaceId}/jobs`, label: "Jobs", icon: Briefcase },
        { href: `/w/${workspaceId}/keys`, label: "API Keys", icon: KeyRound },
        { href: `/w/${workspaceId}/mcp`, label: "MCP Connections", icon: Cpu },
        { href: `/w/${workspaceId}/webhooks`, label: "Webhooks", icon: Webhook },
        { href: `/w/${workspaceId}/audit`, label: "Audit Log", icon: ShieldCheck },
        { href: `/w/${workspaceId}/analytics`, label: "Usage & Analytics", icon: BarChart3 },
        { href: `/w/${workspaceId}/members`, label: "Members & Access", icon: Users },
        { href: `/w/${workspaceId}/settings`, label: "Settings", icon: Settings },
        { href: `/developer/api`, label: "Developer / API", icon: BookOpen },
      ]
    : [{ href: `/developer/api`, label: "Developer / API", icon: FileCode2 }];

  const sidebarContent = (
    <div className="flex h-full flex-col">
      <div className="flex h-16 items-center justify-between border-b border-[hsl(var(--border))] px-4">
        {!collapsed && (
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
            <Activity className="h-5 w-5 text-[hsl(var(--primary))]" />
            <span>Data Collector</span>
          </Link>
        )}
        <button
          type="button"
          aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
          onClick={() => setCollapsed((c) => !c)}
          className="hidden rounded p-1.5 hover:bg-[hsl(var(--muted))] lg:inline-flex"
        >
          {collapsed ? <ChevronRight className="h-4 w-4" /> : <ChevronLeft className="h-4 w-4" />}
        </button>
      </div>

      <nav aria-label="Primary navigation" className="flex-1 space-y-1 overflow-y-auto p-3">
        {navItems.map((item) => {
          const Icon = item.icon;
          const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
          return (
            <Link
              key={item.href}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={`flex items-center gap-3 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
                active
                  ? "bg-[hsl(var(--primary))] text-[hsl(var(--primary-foreground))]"
                  : "text-[hsl(var(--foreground))] hover:bg-[hsl(var(--muted))]"
              }`}
            >
              <Icon className="h-4 w-4 shrink-0" aria-hidden="true" />
              {!collapsed && <span className="truncate">{item.label}</span>}
            </Link>
          );
        })}
      </nav>

      {!collapsed && capsQuery.data && (
        <div className="border-t border-[hsl(var(--border))] p-3 text-xs text-[hsl(var(--muted-foreground))]">
          Role: <span className="font-semibold uppercase">{capsQuery.data.role}</span>
        </div>
      )}
    </div>
  );

  return (
    <div className="flex min-h-screen bg-[hsl(var(--surface))]">
      {/* Desktop sidebar */}
      <aside
        className={`hidden shrink-0 border-r border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))] transition-all lg:block ${
          collapsed ? "w-[72px]" : "w-64"
        }`}
      >
        {sidebarContent}
      </aside>

      {/* Mobile drawer */}
      {mobileOpen && (
        <div className="fixed inset-0 z-50 flex lg:hidden">
          <div className="fixed inset-0 bg-black/50" onClick={() => setMobileOpen(false)} />
          <aside className="relative z-10 w-64 bg-[hsl(var(--surface-elevated))] shadow-xl">
            <button
              type="button"
              aria-label="Close navigation"
              onClick={() => setMobileOpen(false)}
              className="absolute right-3 top-4 rounded p-1 hover:bg-[hsl(var(--muted))]"
            >
              <X className="h-4 w-4" />
            </button>
            {sidebarContent}
          </aside>
        </div>
      )}

      {/* Main area */}
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 flex h-16 items-center justify-between border-b border-[hsl(var(--border))] bg-[hsl(var(--surface-elevated))] px-4 lg:px-6">
          <div className="flex items-center gap-3">
            <button
              type="button"
              aria-label="Open navigation"
              onClick={() => setMobileOpen(true)}
              className="rounded p-1.5 hover:bg-[hsl(var(--muted))] lg:hidden"
            >
              <Menu className="h-5 w-5" />
            </button>
            {wsListQuery.data && wsListQuery.data.items.length > 0 && (
              <label className="flex items-center gap-2 text-sm">
                <span className="hidden text-xs font-medium text-[hsl(var(--muted-foreground))] sm:inline">
                  Workspace
                </span>
                <select
                  aria-label="Switch workspace"
                  value={workspaceId ?? ""}
                  onChange={(e) => handleSwitchWorkspace(e.target.value)}
                  className="h-8 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] px-2.5 text-sm font-medium"
                >
                  {wsListQuery.data.items.map((ws) => (
                    <option key={ws.id} value={ws.id}>
                      {ws.name} ({ws.slug})
                    </option>
                  ))}
                </select>
              </label>
            )}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              aria-label="Toggle color theme"
              onClick={toggleTheme}
              className="rounded-md border border-[hsl(var(--border))] p-2 hover:bg-[hsl(var(--muted))]"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </button>
            {meQuery.data?.email && (
              <span className="hidden text-xs text-[hsl(var(--muted-foreground))] md:inline">
                {meQuery.data.email}
              </span>
            )}
            <button
              type="button"
              onClick={handleLogout}
              className="inline-flex items-center gap-1.5 rounded-md border border-[hsl(var(--border))] px-3 py-1.5 text-xs font-medium hover:bg-[hsl(var(--muted))]"
            >
              <LogOut className="h-3.5 w-3.5" />
              <span>Sign out</span>
            </button>
          </div>
        </header>

        <main className="mx-auto w-full max-w-[1440px] flex-1 p-4 lg:p-6">{children}</main>
      </div>
    </div>
  );
}
