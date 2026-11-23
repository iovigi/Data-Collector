import crypto from "crypto";
import Redis from "ioredis";

export interface SessionData {
  id: string;
  accessToken: string;
  refreshToken: string;
  expiresAt: number; // epoch ms
  userId?: string;
  email?: string;
}

const SESSION_TTL_SECONDS = 60 * 60 * 24 * 7;

// Global in-memory fallback for local dev/test when SESSION_REDIS_URL is not reachable
const globalForSessions = globalThis as unknown as {
  __dcMemorySessions?: Map<string, SessionData>;
  __dcRedisClient?: Redis | null;
  __dcRefreshLocks?: Map<string, Promise<SessionData | null>>;
};

if (!globalForSessions.__dcMemorySessions) {
  globalForSessions.__dcMemorySessions = new Map();
}
if (!globalForSessions.__dcRefreshLocks) {
  globalForSessions.__dcRefreshLocks = new Map();
}

function getRedis(): Redis | null {
  if (globalForSessions.__dcRedisClient !== undefined) {
    return globalForSessions.__dcRedisClient;
  }
  const url = process.env.SESSION_REDIS_URL;
  if (!url) {
    globalForSessions.__dcRedisClient = null;
    return null;
  }
  try {
    const client = new Redis(url, {
      lazyConnect: true,
      maxRetriesPerRequest: 1,
      connectTimeout: 1500,
    });
    client.on("error", () => {
      // Fallback gracefully if Redis is unavailable in local dev
    });
    globalForSessions.__dcRedisClient = client;
    return client;
  } catch {
    globalForSessions.__dcRedisClient = null;
    return null;
  }
}

export function generateSessionId(): string {
  return crypto.randomBytes(32).toString("base64url");
}

export async function saveSession(session: SessionData): Promise<void> {
  globalForSessions.__dcMemorySessions!.set(session.id, session);
  const redis = getRedis();
  if (redis) {
    try {
      await redis.set(
        `dc:web:sess:${session.id}`,
        JSON.stringify(session),
        "EX",
        SESSION_TTL_SECONDS
      );
    } catch {
      // memory store already updated
    }
  }
}

export async function getSession(sessionId: string): Promise<SessionData | null> {
  if (!sessionId) return null;
  const redis = getRedis();
  if (redis) {
    try {
      const raw = await redis.get(`dc:web:sess:${sessionId}`);
      if (raw) {
        return JSON.parse(raw) as SessionData;
      }
    } catch {
      // fall back to memory store
    }
  }
  return globalForSessions.__dcMemorySessions!.get(sessionId) ?? null;
}

export async function deleteSession(sessionId: string): Promise<void> {
  globalForSessions.__dcMemorySessions!.delete(sessionId);
  const redis = getRedis();
  if (redis) {
    try {
      await redis.del(`dc:web:sess:${sessionId}`);
    } catch {
      // ignore
    }
  }
}

export function backendBaseUrl(): string {
  return (process.env.DATA_COLLECTOR_API_INTERNAL_URL || "http://127.0.0.1:8000").replace(
    /\/+$/,
    ""
  );
}

/**
 * Single-flight refresh per session ID so concurrent tabs/requests do not race
 * on backend refresh token rotation.
 */
export async function refreshSessionSingleFlight(sessionId: string): Promise<SessionData | null> {
  const locks = globalForSessions.__dcRefreshLocks!;
  const existing = locks.get(sessionId);
  if (existing) {
    return existing;
  }

  const promise = (async (): Promise<SessionData | null> => {
    const current = await getSession(sessionId);
    if (!current) return null;

    try {
      const resp = await fetch(`${backendBaseUrl()}/api/v1/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: current.refreshToken }),
        cache: "no-store",
      });
      if (!resp.ok) {
        await deleteSession(sessionId);
        return null;
      }
      const data = (await resp.json()) as {
        access_token: string;
        refresh_token: string;
        expires_in: number;
      };
      const updated: SessionData = {
        ...current,
        accessToken: data.access_token,
        refreshToken: data.refresh_token,
        expiresAt: Date.now() + data.expires_in * 1000,
      };
      await saveSession(updated);
      return updated;
    } catch {
      return null;
    }
  })().finally(() => {
    locks.delete(sessionId);
  });

  locks.set(sessionId, promise);
  return promise;
}
