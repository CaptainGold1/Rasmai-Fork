import type { Metadata } from "next";
import { PublicProfile } from "@/components/PublicProfile";
import "../../me/dashboard.css";

// a shared link is for the people it was sent to, not for search engines
export const metadata: Metadata = { title: "A maimai profile · Rasmai", robots: { index: false, follow: false } };

export default async function SharedProfilePage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params;
  return <PublicProfile slug={slug} />;
}
