import React, { Suspense, useState } from "react";
import { useRouter, useSearchParams } from "@/lib/router";
import { Eye, EyeOff, Activity } from "lucide-react";
import { apiAuthPost } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";
import { sanitizeReturnPath } from "@/lib/auth/returnPath";
import { Button, Card, Input } from "@/components/ui/primitives";

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPw, setShowPw] = useState(false);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg(null);
    setLoading(true);
    try {
      await apiAuthPost("/api/auth/login", { email, password });
      const next = sanitizeReturnPath(searchParams.get("next"), "/");
      router.replace(next);
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setErrorMsg("Too many sign-in attempts. Please wait a minute and try again.");
      } else if (err instanceof ApiError) {
        setErrorMsg(err.message);
      } else {
        setErrorMsg("Unable to sign in. Check your connection and try again.");
      }
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[hsl(var(--surface))] p-4">
      <Card className="w-full max-w-md p-8">
        <div className="mb-6 flex items-center gap-2.5">
          <Activity className="h-6 w-6 text-[hsl(var(--primary))]" />
          <div>
            <h1 className="text-xl font-semibold">Data Collector 2.0</h1>
            <p className="text-xs text-[hsl(var(--muted-foreground))]">
              Sign in to your workspace administration console
            </p>
          </div>
        </div>

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium">
              Email address
            </label>
            <Input
              id="email"
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@company.com"
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium">
              Password
            </label>
            <div className="relative">
              <Input
                id="password"
                type={showPw ? "text" : "password"}
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="pr-10"
              />
              <button
                type="button"
                aria-label={showPw ? "Hide password" : "Show password"}
                onClick={() => setShowPw((s) => !s)}
                className="absolute right-2.5 top-2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
              >
                {showPw ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
              </button>
            </div>
          </div>

          {errorMsg && (
            <div
              role="alert"
              className="rounded-md border border-[hsl(var(--destructive))] bg-red-500/10 px-3 py-2 text-sm text-[hsl(var(--destructive))]"
            >
              {errorMsg}
            </div>
          )}

          <Button type="submit" className="w-full" disabled={loading}>
            {loading ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </Card>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[hsl(var(--surface))]" />}>
      <LoginForm />
    </Suspense>
  );
}
