import { clientKey, json } from "@/lib/http";
import { internal, passthrough, unavailable } from "@/lib/internal";
import { apiLimiter } from "@/lib/limiter";

export const dynamic = "force-dynamic";

const SLUG = /^[A-Za-z0-9_-]{16,64}$/;

type Params = { params: Promise<{ slug: string }> };

/** A shared profile. No sign-in: the link is the whole credential, and the bot decides what it carries. */
export async function GET(request: Request, { params }: Params) {
  if (!apiLimiter.allow(clientKey(request))) return json(429, { ok: false, error: "rate_limited" });
  const { slug } = await params;
  if (!SLUG.test(slug ?? "")) return json(404, { ok: false, error: "not_found" });
  try {
    return passthrough(await internal(`/internal/public/${slug}`, { client: clientKey(request) }));
  } catch {
    return unavailable();
  }
}
