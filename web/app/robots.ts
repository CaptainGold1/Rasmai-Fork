import type { MetadataRoute } from "next";
import { env } from "@/lib/env";

export const dynamic = "force-dynamic";

export default function robots(): MetadataRoute.Robots {
  const site = env.publicUrl();
  return {
    rules: [
      {
        userAgent: "*",
        allow: "/",
        // a shared profile is for whoever was given the link, the rest is someone's own data or
        // a sign-in step. None of it should turn up in a search result.
        disallow: ["/me", "/me/", "/p/", "/connect", "/connected", "/link/?", "/api/", "/auth/", "/invite"],
      },
    ],
    sitemap: `${site}/sitemap.xml`,
    host: site,
  };
}
