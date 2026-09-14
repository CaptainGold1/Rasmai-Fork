import type { Metadata } from "next";
import { Contact, Doc, SITE_URL } from "@/components/Doc";

export const metadata: Metadata = {
  title: "Privacy",
  description: "What Rasmai stores about you, why, and how to delete all of it.",
  alternates: { canonical: "/privacy/" },
  openGraph: { title: "Privacy · Rasmai", description: "What Rasmai stores about you, why, and how to delete all of it.", url: "/privacy/", images: ["/opengraph-image"] },
};

export default function PrivacyPage() {
  return (
    <Doc
      tag="privacy"
      title={
        <>
          What Rasmai <em>keeps</em>, and why.
        </>
      }
      intro="Rasmai is a Discord bot that reads your maimai DX scores and tells you what to grind. This page lists exactly what it stores, for how long, and how to remove it. There is no tracking, no analytics and no advertising."
    >
      <h2>What is stored</h2>
      <p>
        When you link an account with <code>/login</code>, the bot keeps the following in one database file on the server it runs on:
      </p>
      <ul>
        <li>
          <b>Your Discord user ID</b>, so the bot knows which maimai account is yours when you run a command.
        </li>
        <li>
          <b>Your maimai region</b> (international, Japan or China).
        </li>
        <li>
          <b>A maimai DX NET session key.</b> This is the <code>clal</code> cookie the official site issues after you sign
          in on SEGA&apos;s page. It is <b>not your password</b>; Rasmai never sees your SEGA ID or password. The key is
          encrypted before it is written to disk.
        </li>
        <li>
          <b>Your player profile</b> as shown on maimai DX NET: player name, rating, title, dan and avatar, refreshed each time
          your scores are read.
        </li>
        <li>
          <b>A compact copy of your scores</b> (chart, achievement, rank, rating, lamps and DX score) from your most recent
          read. It powers the dashboard, <code>/compare</code> and <code>/export</code> without re-reading the official site,
          and is replaced on every read.
        </li>
        <li>
          <b>Your play history.</b> Every play the bot sees on the recent-plays page (chart, achievement, DX score, lamps, track
          and the time it was played), and each new best it notices on a read. maimai DX NET itself shows only your last fifty
          plays; this copy is what lets the score graphs, <code>/progress</code>, the dashboard&apos;s Recent tab and the
          model&apos;s check of itself look further back. It grows for as long as your account is linked and is not trimmed.
        </li>
        <li>
          <b>Rating readings over time</b> (rating, best-50 totals, chart and play counts, timestamp), one per read where
          something moved, so <code>/progress</code> can draw your rating over time.
        </li>
        <li>
          <b>Per-chart play counts</b>, cached for 12 hours, or until you play the chart again, so the bot does not have to
          re-read hundreds of pages every time.
        </li>
        <li>
          <b>Your settings</b> from <code>/settings</code>: default layout, default targets and difficulty, and three opt-ins
          that are <b>off unless you turn them on</b>: letting other people run <code>/compare</code> against your stored
          scores, appearing on <code>/leaderboard</code> in servers you share with the bot, and a daily read of your
          recent-plays page (below). With the first two off, nobody else can see anything about your account through the bot.
        </li>
        <li>
          <b>One-time login codes</b>, stored only as hashes. They work once, expire after 10 minutes and are deleted within a
          day.
        </li>
      </ul>
      <p>
        Scores are read when you run a command, press the read-now button on the dashboard, or, if you turned on{" "}
        <code>/settings history</code>, once a day in the background. That daily read signs in with your stored session key
        and loads only the recent-plays page, so plays are not lost between commands; the time it ran and how many plays it
        found are shown by <code>/settings</code>.
      </p>

      <h2>The website</h2>
      <ul>
        <li>
          <b>Dashboard sign-in.</b> Signing in with Discord sets one cookie holding a signed copy of your Discord ID, name and
          avatar address, valid for 30 days, plus a short-lived cookie during the sign-in handshake. Only your Discord ID and
          name are requested; the bot does not ask for your server list and posts nothing. Signing out clears the cookie.
        </li>
        <li>
          <b>Human check.</b> The sign-in and account-connect pages show a Cloudflare Turnstile check, which loads a script
          from Cloudflare. Cloudflare also fronts this site, so it handles requests to it the way any content network does.
          Both are covered by{" "}
          <a href="https://www.cloudflare.com/privacypolicy/" rel="noopener noreferrer">
            Cloudflare&apos;s privacy policy
          </a>
          .
        </li>
        <li>
          <b>Home-screen app.</b> The site can be installed on a phone. Its service worker caches only the site&apos;s own static
          files (scripts, styles, fonts and icons) so the shell opens offline; scores, sign-in and everything under the API are
          never cached on the device.
        </li>
        <li>No analytics, no advertising and no other third-party scripts.</li>
      </ul>

      <h2>What is not stored</h2>
      <ul>
        <li>Your SEGA ID, password, Aime card number or payment details. Sign-in happens on SEGA&apos;s own site.</li>
        <li>
          Your IP address. Sign-in attempts and reads are rate-limited with a short-lived in-memory counter that is never
          written to disk.
        </li>
        <li>Messages you send in Discord. The bot only responds to its own slash commands and does not read chat.</li>
        <li>Anything about people who have not linked an account.</li>
      </ul>

      <h2>Who else sees it</h2>
      <ul>
        <li>
          <b>SEGA (maimai DX NET).</b> The bot uses your session key to load your score pages from the official site, the
          same pages you see when you sign in yourself.
        </li>
        <li>
          <b>Discord.</b> The bot&apos;s replies, including the images it generates from your scores, are posted to Discord in the
          channel where you ran the command, and are subject to{" "}
          <a href="https://discord.com/privacy" rel="noopener noreferrer">
            Discord&apos;s privacy policy
          </a>
          . Use commands in a private channel if you would rather other members did not see your results.
        </li>
        <li>
          <b>Cloudflare</b>, as the network in front of the website and the provider of the human check, as described above.
        </li>
        <li>
          <b>Nobody else.</b> Data is not sold, shared or used for advertising, and there is no analytics or telemetry.
        </li>
      </ul>

      <h2>How long it is kept, and how to delete it</h2>
      <p>
        Your linked account, its scores and its play history stay until you remove them; nothing expires on its own except the
        session key, which stops working when SEGA expires it, and the caches listed above.
      </p>
      <ul>
        <li>
          <b>Yourself, at once.</b> Run <code>/delete-account</code> in Discord, or press <b>unlink</b> on the dashboard&apos;s Account
          tab. Either deletes your session key, profile, stored scores, play history, rating readings, settings, play-count
          cache and any login codes immediately. Your dashboard sign-in cookie stays until you sign out or it expires; it holds
          nothing but your Discord ID and name.
        </li>
        <li>
          <b>By contact.</b> If you cannot use either, for example because you no longer have access to the Discord account, or
          you want everything about you removed including the bot&apos;s memory that you were ever linked, write to{" "}
          <Contact />. Say which Discord account or maimai player name the data belongs to; the data is deleted by hand,
          normally within a few days, and you get a reply when it is done. The same address handles a request for a copy of
          what is stored, though <code>/export</code> and the dashboard&apos;s <b>download JSON</b> button give you that at any
          time.
        </li>
      </ul>
      <p>
        Replies the bot posted in Discord are messages in Discord, not data held by Rasmai; delete them there if you want
        them gone.
      </p>

      <h2>Security</h2>
      <ul>
        <li>Session keys are encrypted at rest with a key that lives only on the server.</li>
        <li>Login links are single-use, tied to your Discord account, and expire after ten minutes.</li>
        <li>All connections to this site and to maimai DX NET use HTTPS with certificate verification.</li>
        <li>Sign-in attempts are rate-limited and gated by a human check.</li>
      </ul>

      <h2>Age</h2>
      <p>Rasmai is used through Discord, so Discord&apos;s minimum age applies. It is not directed at children.</p>

      <h2>Changes and contact</h2>
      <p>
        If this policy changes, the effective date above changes with it. Questions and deletion requests go to <Contact />.
        This policy applies to the bot and to <code>{SITE_URL.replace("https://", "")}</code>.
      </p>
    </Doc>
  );
}
