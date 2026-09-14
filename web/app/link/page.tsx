import type { Metadata } from "next";
import { Shell } from "@/components/Shell";
import { Walkthrough } from "@/components/Walkthrough";

export const metadata: Metadata = {
  title: "Link your maimai account",
  description: "Connect maimai DX NET to Rasmai in about a minute, on a computer or an iPhone, with the whole thing on video.",
  alternates: { canonical: "/link/" },
  openGraph: { title: "Link your maimai account · Rasmai", description: "Connect maimai DX NET to Rasmai in about a minute, on a computer or an iPhone, with the whole thing on video.", url: "/link/" , images: ["/opengraph-image"] },
};

export default function LinkPage() {
  return (
    <Shell tag="link" lit={1} footLeft="not affiliated with SEGA">
      <h1>
        Link your <em>maimai</em> account.
      </h1>
      <p className="lede">
        Once linked, the bot reads your scores and tells you which charts to grind for the most rating, picked for how
        you actually play.
      </p>

      <section className="step walk-step">
        <div className="n" aria-hidden="true">
          ▶
        </div>
        <div>
          <h2>Watch it done first</h2>
          <p>The whole thing on the device you are holding. No sound, about a minute.</p>
          <Walkthrough />
        </div>
      </section>

      <section className="step">
        <div className="n">1</div>
        <div>
          <h2>Ask the bot for your link</h2>
          <p>
            In Discord, run <code>/login</code>. It replies with a private link back here with your login code already
            filled in.
          </p>
        </div>
      </section>
      <section className="step">
        <div className="n">2</div>
        <div>
          <h2>Sign in at my-aime, then authenticate</h2>
          <p>
            Sign in at <a href="https://my-aime.net/en/">my-aime.net</a> with the account you play on, then open the Aime authentication
            from the setup page. It uses that sign-in and takes you to the gateway. About a minute.
          </p>
        </div>
      </section>
      <section className="step">
        <div className="n">3</div>
        <div>
          <h2>Grind</h2>
          <p>
            Back in Discord: <code>/analyze</code> for the poster, <code>/plan</code> for your route to the next thousand.
          </p>
        </div>
      </section>

      <div className="aside">
        <b>Already linked?</b> Everything the bot knows about your scores is also on the web:{" "}
        <a href="/me/">open your dashboard</a> and sign in with Discord.
      </div>
    </Shell>
  );
}
