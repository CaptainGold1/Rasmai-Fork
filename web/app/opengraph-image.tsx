import { ImageResponse } from "next/og";

export const runtime = "nodejs";
export const alt = "Rasmai · know what to play next";
export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/** The card that shows when a Rasmai link is pasted anywhere. Drawn at build time from the brand. */
export default async function Image() {
  return new ImageResponse(
    (
      <div
        style={{
          width: "100%",
          height: "100%",
          display: "flex",
          flexDirection: "column",
          justifyContent: "center",
          padding: "0 92px",
          background: "#14121c",
          color: "#f4f0e6",
          fontFamily: "sans-serif",
        }}
      >
        <div style={{ display: "flex", fontSize: 26, letterSpacing: 6, color: "#918ba6", textTransform: "uppercase" }}>
          a discord bot for maimai dx
        </div>
        <div style={{ display: "flex", fontSize: 96, fontWeight: 800, lineHeight: 1.05, marginTop: 18 }}>
          Know what to
        </div>
        <div style={{ display: "flex", fontSize: 96, fontWeight: 800, lineHeight: 1.05, color: "#ff5c9f" }}>
          play next.
        </div>
        <div style={{ display: "flex", fontSize: 30, color: "#c6c0d4", marginTop: 30, maxWidth: 900 }}>
          Rasmai reads your scores and picks the charts worth the most rating, with the odds on each.
        </div>
        <div style={{ display: "flex", marginTop: 46, fontSize: 26, color: "#45d6f2", letterSpacing: 2 }}>
          rasmai.lol
        </div>
      </div>
    ),
    size,
  );
}
