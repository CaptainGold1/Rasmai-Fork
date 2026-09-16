"use client";

import { useEffect, useRef, useState } from "react";
import { getJSON, postJSON, type Beta as BetaState, type BetaFeature } from "./api";
import { Label } from "./bits";

const POLL_MS = 4000;

/** "about 12 minutes left", from seconds. */
function left(seconds: number): string {
  if (seconds <= 0) return "";
  if (seconds < 60) return "less than a minute left";
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `about ${minutes} minute${minutes === 1 ? "" : "s"} left`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `about ${hours}h${rest ? ` ${rest}m` : ""} left`;
}

/** How far a feature's groundwork has got, while it is still going. */
function Progress({ feature }: { feature: BetaFeature }) {
  const total = feature.total ?? 0;
  const done = feature.done ?? 0;
  if (!total || !feature.waiting) return null;
  const percent = Math.min(100, Math.max(0, feature.percent ?? 0));
  const eta = left(feature.eta ?? 0);
  return (
    <span className="crawl">
      <span
        className="crawl-bar"
        role="progressbar"
        aria-valuenow={Math.round(percent)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="charts read so far"
      >
        <span style={{ width: `${percent}%` }} />
      </span>
      <span className="crawl-said mono">
        {done.toLocaleString()} / {total.toLocaleString()} charts · {percent.toFixed(1)}%{eta ? ` · ${eta}` : ""}
      </span>
    </span>
  );
}

/** Features that work but are not finished. Each is off until its owner turns it on. */
export function Beta({ state, onChange }: { state: BetaState; onChange: (next: BetaState) => void }) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState("");
  const latest = useRef(onChange);
  latest.current = onChange;

  // while groundwork is still running, keep the bar moving without the person reloading the page
  const running = state.features.some((f) => (f.waiting ?? 0) > 0);
  useEffect(() => {
    if (!running) return;
    let alive = true;
    const timer = setInterval(() => {
      getJSON<BetaState>("/api/me/beta")
        .then((next) => {
          if (alive) latest.current(next);
        })
        .catch(() => undefined);
    }, POLL_MS);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [running]);

  const toggle = (key: string, on: boolean) => {
    setBusy(true);
    setNote("");
    postJSON<BetaState>("/api/me/beta", { on: { [key]: on } })
      .then((next) => {
        onChange(next);
        const feature = next.features.find((f) => f.key === key);
        setNote(
          !on
            ? "Off from your next read."
            : feature && feature.ready === false
              ? "On, but not enough is read yet to measure anything. Your traits will change once it is."
              : "On from your next read. Use refresh above to see it now.",
        );
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
                <Progress feature={feature} />
                {feature.status && !feature.waiting && <span className="mono hint ok">{feature.status}</span>}
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
