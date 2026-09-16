"use client";

import { useState } from "react";
import { postJSON, type Sharing as SharingState } from "./api";
import { Label } from "./bits";

const SECTIONS: { key: keyof SharingState["sections"]; label: string; note: string }[] = [
  { key: "best50", label: "Best 50", note: "the fifty charts your rating is made of" },
  { key: "traits", label: "Traits", note: "where you lose points and where you shine" },
  { key: "recent", label: "Recent plays", note: "the last twenty plays the bot has seen" },
  { key: "areas", label: "Areas", note: "how far along each area you are" },
];

/** The public profile: a link anyone can open, carrying only the sections that are switched on. */
export function Sharing({ state, onChange }: { state: SharingState; onChange: (next: SharingState) => void }) {
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const [note, setNote] = useState("");

  const save = (body: Record<string, unknown>) => {
    setBusy(true);
    setNote("");
    postJSON<SharingState>("/api/me/sharing", body)
      .then(onChange)
      .catch((e: Error) => setNote(e.message || "could not save that"))
      .finally(() => setBusy(false));
  };

  const copy = () => {
    navigator.clipboard
      .writeText(state.url)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      })
      .catch(() => setNote("could not copy; select the link instead"));
  };

  return (
    <section className="ledger">
      <div className="ledger-head">
        <Label info="A page anyone with the link can open. Your Discord account is never on it and it is not indexed by search engines. Turning it off stops the link working straight away.">
          public profile
        </Label>
        <span className={`mono hint${state.on ? " ok" : ""}`}>{state.on ? "shared" : "private"}</span>
      </div>

      <p className="hint">
        Off by default. Shows your name, rating and play count, plus the sections you pick.
      </p>

      <div className="btn-row">
        <button type="button" className={state.on ? "button ghost" : "button"} onClick={() => save({ on: !state.on })} disabled={busy}>
          {state.on ? "stop sharing" : "create a public link"}
        </button>
        {state.on && (
          <button type="button" className="button ghost" onClick={() => save({ on: true, rotate: true })} disabled={busy}>
            new link
          </button>
        )}
      </div>

      {state.on && state.url && (
        <div className="share-link">
          <code>{state.url}</code>
          <button type="button" className="button ghost" onClick={copy}>
            {copied ? "copied" : "copy"}
          </button>
        </div>
      )}

      {state.on && (
        <ul className="share-toggles">
          {SECTIONS.map((section) => (
            <li key={section.key}>
              <label>
                <input
                  type="checkbox"
                  checked={state.sections[section.key]}
                  disabled={busy}
                  onChange={(e) => save({ sections: { [section.key]: e.target.checked } })}
                />
                <span>
                  <b>{section.label}</b>
                  <span className="dim">{section.note}</span>
                </span>
              </label>
            </li>
          ))}
        </ul>
      )}

      {note && <p className="hint">{note}</p>}
      {state.on && <p className="hint">A new link stops the old one working, so anything already passed around goes dead.</p>}
    </section>
  );
}
