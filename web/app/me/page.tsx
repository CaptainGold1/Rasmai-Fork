import type { Metadata } from "next";
import { Dash } from "@/components/dash/Dash";
import "./dashboard.css";

export const metadata: Metadata = {
  // somebody's own scores: never a search result
  robots: { index: false, follow: false },
  title: "Rasmai · dashboard",
  description: "Your maimai scores, best 50 and what to play next, as the bot sees them.",
};

export default function MePage() {
  return <Dash />;
}
