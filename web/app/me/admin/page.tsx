import type { Metadata } from "next";
import { Admin } from "@/components/dash/Admin";
import "../dashboard.css";

export const metadata: Metadata = { title: "Developer · Rasmai", robots: { index: false, follow: false } };

export default function AdminPage() {
  return <Admin />;
}
