"use client";

import { useEffect, useState } from "react";
import { Ring } from "@/components/Ring";
import { ThemeToggle } from "@/components/Theme";
import { Chip, Empty, Label, num, pct, when } from "./dash/bits";

type Chart = {
  title: string; difficulty: string; type: string; level: string; constant: number;
  accuracy: number; rank: string; rating: number; fc: string; fs: string;
};
type Shared = {
  name: string; title: string; dan: string; region: string; rating: number; plays: number; charts: number;
  updatedAt: string;
  shows: { best50: boolean; traits: boolean; recent: boolean; areas: boolean };
  best50?: { new: Chart[]; old: Chart[] };
  recent?: { title: string; difficulty: string; type: string; achievement: number; rank: string; day: string }[];
  traits?: { label: string; offset: number; count: number; kind: string }[];
  areas?: { name: string; english: string; distance: number; state: string }[];
  history?: { recordedAt: string; rating: number }[];
};

function Line({ points }: { points: { recordedAt: string; rating: number }[] }) {
  if (points.length < 2) return null;
  const values = points.map((p) => p.rating);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = Math.max(1, high - low);
  const path = points
    .map((p, i) => `${(100 * i) / (points.length - 1)},${30 - (28 * (p.rating - low)) / span}`)
    .join(" ");
  return (
    <svg className="share-spark" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label={`rating from ${low} to ${high}`}>
      <polyline points={path} fill="none" stroke="var(--pink)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function Pool({ title, rows, size }: { title: string; rows: Chart[]; size: number }) {
  if (!rows.length) return null;
  return (
    <section className="ledger">
      <div className="ledger-head">
        <Label>
          {title} · {rows.length}/{size}
        </Label>
        <span className="mono hint">{num(rows.reduce((sum, r) => sum + r.rating, 0))} rating</span>
      </div>
      <div className="scroll">
        <table className="tbl compact b50 keep">
          <tbody>
            {rows.map((r, i) => (
              <tr key={`${r.title}|${r.type}|${r.difficulty}`}>
                <td className="c-n">{i + 1}</td>
                <td className="c-title">
                  <span className="title">{r.title}</span>
                  <Chip difficulty={r.difficulty} level={r.level} constant={r.constant} type={r.type} />
                </td>
                <td className="c-num mono c-acc">
                  {pct(r.accuracy)} <b>{r.rank}</b>
                </td>
                <td className="c-num mono strong c-rating">{r.rating}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

export function PublicProfile({ slug }: { slug: string }) {
  const [data, setData] = useState<Shared | null>(null);
  const [gone, setGone] = useState(false);

  useEffect(() => {
    fetch(`/api/public/${encodeURIComponent(slug)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        setData((await r.json()) as Shared);
      })
      .catch(() => setGone(true));
  }, [slug]);

  if (gone) {
    return (
      <div className="frame dash">
        <header className="masthead">
          <a className="home" href="/">
            <Ring lit={0} size={34} />
          </a>
          <div className="wordmark">
            Ras<span>mai</span>
          </div>
          <ThemeToggle />
        </header>
        <div className="gate">
          <h1>
            This profile is <em>not shared</em>.
          </h1>
          <p className="lede">The link may have been turned off, or replaced with a new one. Ask whoever sent it for the current link.</p>
          <a className="button" href="/">
            what Rasmai does →
          </a>
        </div>
      </div>
    );
  }
  if (!data) {
    return (
      <div className="frame dash">
        <div className="gate">
          <p className="hint">Loading…</p>
        </div>
      </div>
    );
  }

  const weak = (data.traits ?? []).filter((t) => t.offset < 0).sort((a, b) => a.offset - b.offset);
  const strong = (data.traits ?? []).filter((t) => t.offset > 0).sort((a, b) => b.offset - a.offset);
  return (
    <div className="frame dash">
      <header className="masthead">
        <a className="home" href="/">
          <Ring lit={0} size={34} />
        </a>
        <div className="wordmark">
          Ras<span>mai</span>
        </div>
        <ThemeToggle />
      </header>

      <main className="panel">
        <section className="ident">
          <div className="ident-who">
            <div className="label">
              {data.region.toUpperCase()} · shared profile
            </div>
            <h1>{data.name}</h1>
            <div className="ident-sub mono">
              {[data.dan, data.title].filter(Boolean).join(" · ") || "no title read yet"} · {num(data.plays)} plays · read{" "}
              {when(data.updatedAt)}
            </div>
          </div>
          <div className="readout big">
            <span className="lbl">rating</span>
            <span className="val">{num(data.rating)}</span>
            <span className="lbl">charts</span>
            <span className="val">{num(data.charts)}</span>
          </div>
        </section>

        {data.history && data.history.length > 1 && (
          <section className="ledger">
            <div className="ledger-head">
              <Label>rating over time</Label>
              <span className="mono hint">{data.history.length} readings</span>
            </div>
            <Line points={data.history} />
          </section>
        )}

        {data.best50 && (
          <div className="two-up wide-right">
            <Pool title="new version" rows={data.best50.new} size={15} />
            <Pool title="older versions" rows={data.best50.old} size={35} />
          </div>
        )}

        {data.traits && data.traits.length > 0 && (
          <section className="ledger">
            <div className="ledger-head">
              <Label>how they play</Label>
              <span className="mono hint">against their own curve</span>
            </div>
            <div className="two-up">
              <div>
                <div className="ledger-head">
                  <Label>where they lose points</Label>
                </div>
                {weak.length ? (
                  <ul className="traits">
                    {weak.map((t) => (
                      <li key={`w${t.label}`}>
                        <span className="mono trait-offset down">{t.offset.toFixed(2)}</span>
                        <span className="trait-label">{t.label}</span>
                        <span className="mono dim">{t.count}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">Nothing sits below their curve.</p>
                )}
              </div>
              <div>
                <div className="ledger-head">
                  <Label>where they shine</Label>
                </div>
                {strong.length ? (
                  <ul className="traits">
                    {strong.map((t) => (
                      <li key={`s${t.label}`}>
                        <span className="mono trait-offset up">+{t.offset.toFixed(2)}</span>
                        <span className="trait-label">{t.label}</span>
                        <span className="mono dim">{t.count}</span>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="hint">Nothing sits above their curve yet.</p>
                )}
              </div>
            </div>
          </section>
        )}

        {data.recent && (
          <section className="ledger">
            <div className="ledger-head">
              <Label>recent plays</Label>
              <span className="mono hint">newest first</span>
            </div>
            {data.recent.length === 0 ? (
              <Empty>No plays recorded yet.</Empty>
            ) : (
              <table className="tbl compact nojacket">
                <tbody>
                  {data.recent.map((p, i) => (
                    <tr key={`${p.title}${p.day}${i}`}>
                      <td className="c-title">
                        <span className="title">{p.title}</span>
                        <Chip difficulty={p.difficulty} type={p.type} />
                      </td>
                      <td className="c-num mono strong">
                        {pct(p.achievement, 4)} <b>{p.rank}</b>
                      </td>
                      <td className="c-num mono dim">{p.day}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        )}

        {data.areas && data.areas.length > 0 && (
          <section className="ledger">
            <div className="ledger-head">
              <Label>area travel</Label>
              <span className="mono hint">{data.areas.length} under way or finished</span>
            </div>
            <ul className="areas compact">
              {data.areas.map((a) => (
                <li key={a.name} className="area">
                  <span className="area-name">
                    {a.name}
                    {a.english ? <span className="area-english">{a.english}</span> : null}
                  </span>
                  <span className="mono dim">
                    {num(a.distance)} km{a.state === "completed" ? " · done" : ""}
                  </span>
                </li>
              ))}
            </ul>
          </section>
        )}

        <footer className="foot">
          <span>
            Shared with Rasmai · <a href="/">what this is</a> · not affiliated with SEGA
          </span>
          <span>only what this player chose to share is on this page</span>
        </footer>
      </main>
    </div>
  );
}
