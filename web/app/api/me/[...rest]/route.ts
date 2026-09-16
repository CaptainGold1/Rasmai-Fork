import { clientKey, json, sameOrigin } from "@/lib/http";
import { internal, passthrough, unavailable } from "@/lib/internal";
import { apiLimiter } from "@/lib/limiter";
import { currentUser } from "@/lib/session";

export const dynamic = "force-dynamic";

type Params = { params: Promise<{ rest: string[] }> };

const SAFE = /^[a-z-]{1,32}$/;
const IMPORT_BYTES = 4 * 1024 * 1024;

function tail(rest: string[]): string | null {
  const parts = rest.filter(Boolean);
  if (!parts.length || !parts.every((p) => SAFE.test(p))) return null;
  return parts.join("/");
}

/** Everything under /api/me/: charts, picks, new, recent, export, refresh status. */
export async function GET(request: Request, { params }: Params) {
  if (!apiLimiter.allow(clientKey(request))) return json(429, { ok: false, error: "rate_limited" });
  const user = currentUser(request);
  if (!user) return json(401, { ok: false, error: "signed_out" });
  const path = tail((await params).rest);
  if (!path) return json(404, { ok: false, error: "not_found" });
  try {
    return passthrough(await internal(`/internal/me/${path}`, { user, query: new URL(request.url).searchParams }));
  } catch {
    return unavailable();
  }
}

/** Refresh (start a score read), unlink, import, sharing and beta switches. */
export async function POST(request: Request, { params }: Params) {
  if (!apiLimiter.allow(clientKey(request))) return json(429, { ok: false, error: "rate_limited" });
  if (!sameOrigin(request)) return json(403, { ok: false, error: "cross_origin" });
  const user = currentUser(request);
  if (!user) return json(401, { ok: false, error: "signed_out" });
  const path = tail((await params).rest);
  if (!path || !["refresh", "unlink", "import", "sharing", "beta"].includes(path)) return json(404, { ok: false, error: "not_found" });
  let body: unknown = {};
  if (path === "sharing" || path === "beta") {
    try {
      body = JSON.parse(await request.text());
    } catch {
      return json(400, { ok: false, error: "bad_json" });
    }
  }
  if (path === "import") {
    if (Number(request.headers.get("content-length") ?? 0) > IMPORT_BYTES) return json(413, { ok: false, error: "too_large" });
    const text = await request.text();
    if (text.length > IMPORT_BYTES) return json(413, { ok: false, error: "too_large" });
    try {
      body = JSON.parse(text);
    } catch {
      return json(400, { ok: false, error: "bad_json" });
    }
    if (!body || typeof body !== "object" || Array.isArray(body)) return json(400, { ok: false, error: "bad_export" });
  }
  try {
    return passthrough(await internal(`/internal/me/${path}`, { method: "POST", user, client: clientKey(request), body }));
  } catch {
    return unavailable();
  }
}
