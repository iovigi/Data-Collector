"use client";

import React, { createContext, useCallback, useContext, useEffect, useState } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ApiError } from "@/lib/api/errors";

type Theme = "light" | "dark";

interface ThemeContextValue {
  theme: Theme;
  toggleTheme: () => void;
}

const ThemeContext = createContext<ThemeContextValue>({
  theme: "light",
  toggleTheme: () => {},
});

export function useTheme() {
  return useContext(ThemeContext);
}

export interface ToastItem {
  id: string;
  title: string;
  description?: string;
  variant?: "default" | "success" | "error";
}

interface ToastContextValue {
  toast: (item: Omit<ToastItem, "id">) => void;
}

const ToastContext = createContext<ToastContextValue>({
  toast: () => {},
});

export function useToast() {
  return useContext(ToastContext);
}

export function Providers({ children }: { children: React.ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 15_000,
            retry: (failureCount, error) => {
              if (error instanceof ApiError && [401, 403, 404, 422].includes(error.status)) {
                return false;
              }
              return failureCount < 1;
            },
          },
        },
      })
  );

  const [theme, setTheme] = useState<Theme>("light");
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  useEffect(() => {
    const saved = window.localStorage.getItem("dc-theme");
    if (saved === "dark" || saved === "light") {
      setTheme(saved);
      document.documentElement.classList.toggle("dark", saved === "dark");
    }
  }, []);

  const toggleTheme = useCallback(() => {
    setTheme((prev) => {
      const next = prev === "light" ? "dark" : "light";
      window.localStorage.setItem("dc-theme", next);
      document.documentElement.classList.toggle("dark", next === "dark");
      return next;
    });
  }, []);

  const toast = useCallback((item: Omit<ToastItem, "id">) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((prev) => [...prev, { ...item, id }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4500);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      <ThemeContext.Provider value={{ theme, toggleTheme }}>
        <ToastContext.Provider value={{ toast }}>
          {children}
          <div
            aria-live="polite"
            className="fixed bottom-4 right-4 z-50 flex flex-col gap-2 max-w-sm"
          >
            {toasts.map((t) => (
              <div
                key={t.id}
                role="status"
                className={`rounded-lg border px-4 py-3 shadow-lg text-sm bg-[hsl(var(--surface-elevated))] border-[hsl(var(--border))] ${
                  t.variant === "error"
                    ? "border-l-4 border-l-[hsl(var(--destructive))]"
                    : t.variant === "success"
                      ? "border-l-4 border-l-[hsl(var(--success))]"
                      : ""
                }`}
              >
                <div className="font-medium">{t.title}</div>
                {t.description && (
                  <div className="mt-0.5 text-xs text-[hsl(var(--muted-foreground))]">
                    {t.description}
                  </div>
                )}
              </div>
            ))}
          </div>
        </ToastContext.Provider>
      </ThemeContext.Provider>
    </QueryClientProvider>
  );
}
