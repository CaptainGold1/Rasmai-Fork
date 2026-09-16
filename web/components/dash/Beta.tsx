"use client";

import { useState } from "react";
import { postJSON, type Beta as BetaState } from "./api";
import { Label } from "./bits";

/** Features that work but are not finished. Each is off until its owner turns it on. */
export function Beta({ state, onChange }: { state: BetaState; onChange: (next: BetaState) => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");

  const toggle = (key: string, on: boolean) => {
    setBusy(true);
    setNote("");
    postJSON<BetaState>("/api/me/beta", { on: { [key]: on } })
      .then((next) => {
        onChange(next);
        const feature = next.features.find((f) => f.key === key);
        setNote(!on ? "Off from your next read."
          : feature && feature.ready === false ? "On, but the charts are still being read. Your traits will change once that finishes."
          : "On from your next read. Use refresh above to see it now.");
      })
      .catch((e: Error) => setNote(e.message || "could not save that"))
      .finally(() => setBusy(false));
  };

  const count = Object.values(state.on).filter(Boolean).length;

  return (
    <section className="ledger">
      <div className="ledger-head">
        <Label info="Work that is finished enough to use and not finished enough to be on for everyone. Turning one off puts everything back the way it was: nothing is kept that depends on it.">
          beta
        </Label>
        <span className={`mono hint${count ? " ok" : ""}`}>{count ? `${count} on` : "none on"}</span>
      </div>

      <ul className="share-toggles">
        {state.features.map((feature) => (
          <li key={feature.key}>
            <label>
              <input
                type="checkbox"
                checked={Boolean(state.on[feature.key])}
                disabled={busy}
                onChange={(e) => toggle(feature.key, e.target.checked)}
              />
              <span>
                <b>{feature.label}</b>
                <span className="dim">{feature.note}</span>
                {feature.status && (
                  <span className={`mono hint${feature.ready ? " ok" : ""}`}>
                    {feature.ready ? feature.status : `${feature.status}; nothing changes until this finishes`}
                  </span>
                )}
              </span>
            </label>
          </li>
        ))}
      </ul>

      {note && <p className="hint">{note}</p>}
      <p className="hint">These change what the model measures, so your traits can move when you switch one on.</p>
    </section>
  );
}
