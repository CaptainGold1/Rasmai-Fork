import type { MetadataRoute } from "next";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

// only the pages that mean something to a stranger. The dashboard, a shared profile and the
// developer page are all behind a link or a sign-in and are marked noindex, so none belong here.
const PAGES: { path: string; changeFrequency: MetadataRoute.Sitemap[number]["changeFrequency"]; priority: number }[] = [
  { path: "/", changeFrequency: "weekly", priority: 1 },
  { path: "/link/", changeFrequency: "monthly", priority: 0.8 },
  { path: "/privacy/", changeFrequency: "yearly", priority: 0.3 },
  { path: "/terms/", changeFrequency: "yearly", priority: 0.3 },
];

export default function sitemap(): MetadataRoute.Sitemap {
  const site = env.publicUrl();
  const now = new Date();
  return PAGES.map(({ path, changeFrequency, priority }) => ({
    url: `${site}${path}`,
    lastModified: now,
    changeFrequency,
    priority,
  }));
}
