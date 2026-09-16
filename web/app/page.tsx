import type { Metadata } from "next";
import { MastheadNav } from "@/components/Shell";
import { ThemeToggle } from "@/components/Theme";
import { ServersNotice } from "@/components/Servers";
import { Ring } from "@/components/Ring";
import "./landing.css";

const FEATURES: { mark: string; title: string; body: string; command: string }[] = [
  {
    mark: "rank_sssp",
    title: "What to grind, for the most rating",
    body: "Reads every chart you have scored, works out where your skill sits from your own results, and lists the charts where a realistic push moves your best-50 the most.",
    command: "/analyze",
  },
  {
    mark: "up",
    title: "Targets that fit you",
    body: "Easier for the surest steps, Balanced for the best expected gain, Challenging for the biggest gains still within reach. Change it on the reply with a dropdown.",
    command: "/analyze challenge",
  },
  {
    mark: "best50",
    title: "A route to your next thousand",
    body: "A chain of realistic targets that add up to the next rating milestone, with the odds of each and the running total.",
    command: "/plan",
  },
  {
    mark: "plays",
    title: "Tonight's credits, spent well",
    body: "Say how many credits you will play. Each goes where gain times odds is highest, a repeat only if the first try missed, warm-ups first, with what the night is worth in rating.",
    command: "/session",
  },
  {
    mark: "new",
    title: "New charts worth a first pass",
    body: "Charts you have never played that fit your level, with an estimate of what a first pass scores. Ask for a focus and it leans toward the traits you lose points on, or the ones you shine on.",
    command: "/new focus",
  },
  {
    mark: "pb",
    title: "Where you lose points",
    body: "Your scores grouped by tempo, note count, era, genre and designer against your own curve, plus the model's check of itself against your recorded plays: range coverage, predicted against real new bests, and the corrections it applied.",
    command: "/profile",
  },
  {
    mark: "diff_master",
    title: "Look anything up",
    body: "One chart with your score, its prediction, what each rank is worth and what the chart asks of your hands, in Japanese or romaji, with the whole song and a score-history graph one button away. Or browse every chart that carries a pattern: streams, hand swaps, slow rotations.",
    command: "/chart  /charts",
  },
  {
    mark: "rasmai",
    title: "When the next thousand lands",
    body: "Your rating over time, the pace it implies, the date each milestone arrives at that pace, and what the route costs in credits at its odds.",
    command: "/progress",
  },
  {
    mark: "festival",
    title: "Read the chart, then read your run",
    body: "Pattern tags from maiノーツ say what a chart is made of before you play it. Afterwards the play log shows each judgement, so you can work out what cost you rather than being told. The numbers are a starting point; the noticing is yours.",
    command: "/charts  /recent play:1",
  },
];

const COMMANDS: [string, string][] = [
  ["/login", "link your maimai DX NET account"],
  ["/analyze", "what to grind, at your chosen level"],
  ["/plan", "route to your next rating milestone"],
  ["/session", "tonight's credits, each spent where it pays most"],
  ["/new", "unplayed charts that fit you, with a focus on your weak spots"],
  ["/chart  /charts", "one chart in depth, and every chart with a given pattern or level"],
  ["/b50  /dxscore", "your best 50 (also /top), DX standings"],
  ["/recent", "your recent plays, or one play in full with play:1"],
  ["/progress", "your rating over time, and when the next thousand lands"],
  ["/compare  /leaderboard", "against a friend, across a server (opt-in)"],
  ["/random  /profile  /export", "a pick, how you play and where you lose points, your data"],
  ["/settings  /invite", "defaults, a daily read that keeps your history complete, the install link"],
];

const SAMPLE = [
  { tier: "expert", label: "EXPERT 13+", title: "Dragoon", from: "99.12", to: "100.50", ranks: "SS → SSS+", odds: "14%", gain: "+22" },
  { tier: "master", label: "MASTER 13", title: "Starlight Disco", from: "98.60", to: "100.50", ranks: "S+ → SSS+", odds: "11%", gain: "+19" },
  { tier: "expert", label: "EXPERT 12+", title: "Oshama Scramble!", from: "99.71", to: "100.50", ranks: "SS+ → SSS+", odds: "19%", gain: "+11" },
  { tier: "master", label: "MASTER 13+", title: "Imitation:Loud Lounge", from: "97.94", to: "99.00", ranks: "S → SS", odds: "26%", gain: "+9" },
];

export const metadata: Metadata = {
  title: "Know what to play next",
  description: "Rasmai reads your maimai DX NET scores and tells you which charts to play next for the most rating, with the odds on each.",
  alternates: { canonical: "/" },
  openGraph: { title: "Know what to play next · Rasmai", description: "Rasmai reads your maimai DX NET scores and tells you which charts to play next for the most rating, with the odds on each.", url: "/" , images: ["/opengraph-image"] },
};

// what the site is, in the shape search engines read. Only facts that are on the page anyway.
const STRUCTURED = {
  "@context": "https://schema.org",
  "@type": "SoftwareApplication",
  name: "Rasmai",
  applicationCategory: "GameApplication",
  applicationSubCategory: "Discord bot",
  operatingSystem: "Any",
  url: "https://rasmai.lol/",
  description:
    "Rasmai reads your maimai DX NET scores and tells you which charts to play next for the most rating, with the odds on each.",
  isAccessibleForFree: true,
  offers: { "@type": "Offer", price: "0", priceCurrency: "USD" },
  author: { "@type": "Person", name: "nek_ng" },
};

export default function LandingPage() {
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(STRUCTURED) }} />
    <div className="frame landing">
      <header className="masthead">
        <Ring lit={0} size={34} />
        <div className="wordmark">
          Ras<span>mai</span>
        </div>
        <MastheadNav current="home" />
        <ThemeToggle />
      </header>
      <ServersNotice />

      <section className="hero">
        <div className="hero-copy">
          <p className="eyebrow">A Discord bot for maimai DX</p>
          <h1>
            Know what to <em>play next</em>.
          </h1>
          <p className="lede">
            Rasmai reads your maimai DX NET scores and tells you which charts to grind for the most rating, picked for how you actually
            play. Rendered images in Discord, a dashboard on the web, and a chart browser that says what a chart asks of you before you play it.
          </p>
          <div className="btn-row">
            <a className="button pink" href="/invite">
              add to Discord
            </a>
            <a className="button ghost" href="/me/">
              open your dashboard
            </a>
          </div>
        </div>
        <div className="hero-ring" aria-hidden="true">
          <Ring size={260} chase />
        </div>
      </section>

      <section className="image-demo" aria-label="What a result looks like">
        <div className="image">
          <div className="image-head">
            <span className="image-eyebrow">what to play next</span>
            <span className="image-name">your name here</span>
            <span className="image-figure">
              <span className="count" aria-label="+61" />
              <small>rating on this image</small>
            </span>
          </div>
          <table>
            <thead>
              <tr>
                <th>#</th>
                <th>Chart</th>
                <th>Achievement</th>
                <th>Rank</th>
                <th>Odds</th>
                <th>Gain</th>
              </tr>
            </thead>
            <tbody>
              {SAMPLE.map((row, i) => (
                <tr key={row.title} style={{ "--i": i } as React.CSSProperties}>
                  <td className="n">{i + 1}</td>
                  <td>
                    <span className="t">{row.title}</span>
                    <span className={`tier ${row.tier}`}>{row.label}</span>
                  </td>
                  <td className="num">
                    {row.from} → <b>{row.to}</b>
                  </td>
                  <td className="num">{row.ranks}</td>
                  <td className="num">{row.odds}</td>
                  <td className="num gain">{row.gain}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="image-foot">
            <span>rasmai · maimai DX · best-50 aware</span>
            <span>illustration · your image uses your scores</span>
          </div>
        </div>
      </section>

      <section className="features">
        {FEATURES.map((f) => (
          <article key={f.title} className="feature">
            <img src={`/marks/${f.mark}.svg`} alt="" width={44} height={44} />
            <h2>{f.title}</h2>
            <p>{f.body}</p>
            <code>{f.command}</code>
          </article>
        ))}
      </section>

      <section className="split">
        <div>
          <h2 className="section-title">Linking takes a minute</h2>
          <p>
            Run <code>/login</code> in Discord and follow the link. You sign in at my-aime.net, open the Aime authentication, then press a
            bookmark once. The
            bot only ever sees the session it needs to read your scores, never your password, and <code>/delete-account</code> deletes
            everything it holds about you.
          </p>
          <a className="button" href="/link/">
            how linking works →
          </a>
        </div>
        <div>
          <h2 className="section-title">Everything on the web too</h2>
          <p>
            Sign in with Discord and see your rating over time, how you play, both best-50 pools, every scored chart with filters, the
            same picks as the bot at each level, and forty unplayed charts to try.
          </p>
          <a className="button ghost" href="/me/">
            open the dashboard →
          </a>
          <p className="hint" style={{ marginTop: 14 }}>
            On a phone, add the dashboard to your home screen and it opens like an app.
          </p>
        </div>
      </section>

      <section className="commands">
        <h2 className="section-title">Commands</h2>
        <ul className="cmds">
          {COMMANDS.map(([cmd, what]) => (
            <li key={cmd}>
              <code>{cmd}</code>
              <span>{what}</span>
            </li>
          ))}
        </ul>
      </section>

      <footer className="foot">
        <span>
          Created by <b>nek_ng</b> · not affiliated with SEGA · <a href="/privacy/">privacy</a> ·{" "}
          <a href="/terms/">terms</a>
        </span>
        {/* <span>
          <a href="https://github.com/Ne-k/razmai">source on GitHub</a>
        </span> */}
      </footer>
    </div>
    </>
  );
}
