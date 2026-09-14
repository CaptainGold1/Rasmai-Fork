import { clientKey, json } from "@/lib/http";
import { internal } from "@/lib/internal";
import { apiLimiter } from "@/lib/limiter";

export const dynamic = "force-dynamic";

const TTL = 30_000;

// the band is on every page, so this is the busiest call the site makes. One answer is good for
// everyone, so it is held briefly: a flood of visitors costs the bot two reads a minute, not one each.
let held: { at: number; body: unknown } | null = null;

/** The banner across every page. No sign-in: it is the same words for everyone who opens the site. */
export async function GET(request: Request) {
  if (!apiLimiter.allow(clientKey(request))) return json(429, { ok: false, error: "rate_limited" });
  if (held && Date.now() - held.at < TTL) return json(200, held.body);
  try {
    const upstream = await internal("/internal/notice");
    if (!upstream.ok) return json(200, held?.body ?? { text: "" });
    const body = await upstream.json();
    held = { at: Date.now(), body };
    return json(200, body);
  } catch {
    // the bot being down is not worth a banner of its own; the page is fine without one
    return json(200, held?.body ?? { text: "" });
  }
}
