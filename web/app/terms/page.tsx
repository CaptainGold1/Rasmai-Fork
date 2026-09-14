import type { Metadata } from "next";
import { Contact, Doc } from "@/components/Doc";

export const metadata: Metadata = {
  title: "Terms",
  description: "The deal, in plain words: what Rasmai is, what you agree to, and what it does not promise.",
  alternates: { canonical: "/terms/" },
  openGraph: { title: "Terms · Rasmai", description: "The deal, in plain words: what Rasmai is, what you agree to, and what it does not promise.", url: "/terms/", images: ["/opengraph-image"] },
};

export default function TermsPage() {
  return (
    <Doc
      tag="terms"
      title={
        <>
          The <em>deal</em>, in plain words.
        </>
      }
      intro="Rasmai is a free, fan-made tool. Using the bot or this site means you agree to the points below. They are short on purpose."
    >
      <h2>What Rasmai is</h2>
      <p>
        Rasmai is a Discord bot that signs in to maimai DX NET on your behalf, reads your scores, and suggests which charts to
        play for the most rating. It is an independent hobby project. It is <b>not affiliated with, endorsed by or supported
        by SEGA</b>. maimai and maimai DX are trademarks of SEGA.
      </p>

      <h2>Your account</h2>
      <ul>
        <li>
          You may only link a maimai account that is yours. Attempting to link, access or interfere with anyone else&apos;s
          account is prohibited.
        </li>
        <li>
          By linking, you authorise Rasmai to read maimai DX NET using your session, in the same way you would in a
          browser. You are responsible for deciding whether that is acceptable to you under SEGA&apos;s own terms for maimai
          DX NET.
        </li>
        <li>
          Keep your login link to yourself. Anyone who has it before it expires can link their maimai account to your
          Discord account.
        </li>
        <li>
          You can delete your account at any time with <code>/delete-account</code>, which removes what the bot holds about you. See the{" "}
          <a href="/privacy/">privacy page</a> for exactly what that is.
        </li>
      </ul>

      <h2>Fair use</h2>
      <ul>
        <li>Do not use the bot or site to probe, overload or attack the service, maimai DX NET, or Discord.</li>
        <li>Commands are rate-limited per user. Working around those limits, or running automated clients against the bot, is not allowed.</li>
        <li>Do not misrepresent Rasmai as an official SEGA service.</li>
      </ul>

      <h2>What you get, and what you do not</h2>
      <ul>
        <li>
          <b>Recommendations are estimates.</b> Rating maths follows the game&apos;s public formula, but chart constants come
          from a community database and may lag behind or differ from your region. Odds and targets are predictions from
          your own history, not promises.
        </li>
        <li>
          <b>The service is provided as is</b>, with no warranty of any kind. It may be unavailable, change, or stop at any
          time, including if maimai DX NET changes in a way that breaks it.
        </li>
        <li>
          <b>Liability is limited</b> to the fullest extent the law allows. The operator is not liable for any loss arising from
          use of, or inability to use, the bot or site, including anything that happens to your SEGA account.
        </li>
      </ul>

      <h2>Ending things</h2>
      <p>
        You can stop using Rasmai whenever you like; <code>/delete-account</code> removes your data. The operator may remove linked
        accounts or restrict access, for example in response to abuse, without notice.
      </p>

      <h2>Changes and contact</h2>
      <p>
        These terms may be updated; the effective date above marks the current version. Continued use after a change means
        you accept it. Questions go to <Contact />.
      </p>
    </Doc>
  );
}
