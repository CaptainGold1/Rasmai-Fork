"use client";

import { useEffect, useMemo, useState } from "react";
import { Ring } from "@/components/Ring";
import { ThemeToggle } from "@/components/Theme";
import { Chip, Empty, Jacket, Label, num, pct, when } from "./dash/bits";
import { Radar, radarAxes } from "./dash/Traits";

type Chart = {
  title: string; difficulty: string; type: string; level: string; constant: number;
  accuracy: number; rank: string; rating: number; fc: string; fs: string; cover: string;
};
type SharedTrait = { label: string; offset: number; count: number; kind: string };
type Shared = {
  name: string; title: string; dan: string; region: string; rating: number; plays: number; charts: number;
  updatedAt: string;
  shows: { best50: boolean; traits: boolean; recent: boolean; areas: boolean };
  best50?: { new: Chart[]; old: Chart[] };
  recent?: { title: string; difficulty: string; type: string; achievement: number; rank: string; day: string; cover: string }[];
  traits?: SharedTrait[];
  traitAxes?: SharedTrait[];
  areas?: { name: string; english: string; distance: number; state: string }[];
  history?: { recordedAt: string; rating: number }[];
};
type Panel = "overview" | "best50" | "traits" | "recent" | "areas";

function Shell({ children, name }: { children: React.ReactNode; name?: string }) {
  return (
    <div className="frame dash">
      <header className="masthead">
        <a className="home" href="/">
          <Ring lit={0} size={34} />
        </a>
        <div className="wordmark">
          Ras<span>mai</span>
        </div>
        {name ? <span className="masthead-tag mono">{name}</span> : null}
        <ThemeToggle />
      </header>
      {children}
    </div>
  );
}

function RatingLine({ points }: { points: { recordedAt: string; rating: number }[] }) {
  if (points.length < 2) return null;
  const values = points.map((p) => p.rating);
  const low = Math.min(...values);
  const high = Math.max(...values);
  const span = Math.max(1, high - low);
  const path = points.map((p, i) => `${(100 * i) / (points.length - 1)},${30 - (28 * (p.rating - low)) / span}`).join(" ");
  return (
    <>
      <svg className="share-spark" viewBox="0 0 100 32" preserveAspectRatio="none" role="img" aria-label={`rating from ${low} to ${high}`}>
        <polyline points={path} fill="none" stroke="var(--pink)" strokeWidth="1.4" vectorEffect="non-scaling-stroke" />
      </svg>
      <div className="admin-axis mono">
        <span>{num(low)}</span>
        <span className="dim">{points.length} readings</span>
        <span>{num(high)}</span>
      </div>
    </>
  );
}

function Pool({ title, rows, size }: { title: string; rows: Chart[]; size: number }) {
  return (
    <section className="ledger">
      <div className="ledger-head">
        <Label>
          {title} · {rows.length}/{size}
        </Label>
        <span className="mono hint">{num(rows.reduce((sum, r) => sum + r.rating, 0))} rating</span>
      </div>
      {rows.length === 0 ? (
        <Empty>Nothing in this pool yet.</Empty>
      ) : (
        <div className="scroll">
          <table className="tbl compact b50 keep">
            <tbody>
              {rows.map((r, i) => (
                <tr key={`${r.title}|${r.type}|${r.difficulty}`}>
                  <td className="c-n">{i + 1}</td>
                  <td className="c-jacket">
                    <Jacket cover={r.cover} size={32} />
                  </td>
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
      )}
    </section>
  );
}

export function PublicProfile({ slug }: { slug: string }) {
  const [data, setData] = useState<Shared | null>(null);
  const [gone, setGone] = useState(false);
  const [panel, setPanel] = useState<Panel>("overview");

  useEffect(() => {
    fetch(`/api/public/${encodeURIComponent(slug)}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(String(r.status));
        setData((await r.json()) as Shared);
      })
      .catch(() => setGone(true));
  }, [slug]);

  const panels = useMemo(() => {
    if (!data) return [];
    const out: { key: Panel; label: string }[] = [{ key: "overview", label: "Overview" }];
    if (data.best50) out.push({ key: "best50", label: "Best 50" });
    if (data.traits?.length) out.push({ key: "traits", label: "Traits" });
    if (data.recent) out.push({ key: "recent", label: "Recent" });
    if (data.areas?.length) out.push({ key: "areas", label: "Areas" });
    return out;
  }, [data]);

  if (gone) {
    return (
      <Shell>
        <div className="gate">
          <h1>
            This profile is <em>not shared</em>.
          </h1>
          <p className="lede">
            The link may have been turned off, or replaced with a new one. Ask whoever sent it for the current link.
          </p>
          <a className="button" href="/">
            what Rasmai does →
          </a>
        </div>
      </Shell>
    );
  }
  if (!data) {
    return (
      <Shell>
        <div className="gate">
          <p className="hint">Loading…</p>
        </div>
      </Shell>
    );
  }

  const weak = (data.traits ?? []).filter((t) => t.offset < 0).sort((a, b) => a.offset - b.offset);
  const strong = (data.traits ?? []).filter((t) => t.offset > 0).sort((a, b) => b.offset - a.offset);
  const best = data.best50 ? [...data.best50.new, ...data.best50.old].sort((a, b) => b.rating - a.rating)[0] : undefined;
  const wheel = radarAxes((data.traitAxes ?? []) as never);

  return (
    <Shell name={data.name}>
      <section className="ident">
        <div className="ident-who">
          <div className="label">{data.region.toUpperCase()} · shared profile</div>
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

      {panels.length > 1 && (
        <nav className="tabs" aria-label="what this profile shares">
          {panels.map((p) => (
            <button key={p.key} type="button" className={panel === p.key ? "on" : ""} onClick={() => setPanel(p.key)}>
              {p.label}
            </button>
          ))}
        </nav>
      )}

      <main className="panel">
        {panel === "overview" && (
          <>
            {data.history && data.history.length > 1 && (
              <section className="ledger">
                <div className="ledger-head">
                  <Label>rating over time</Label>
                  <span className="mono hint">as the bot has read it</span>
                </div>
                <RatingLine points={data.history} />
              </section>
            )}
            <section className="ledger">
              <div className="ledger-head">
                <Label>at a glance</Label>
              </div>
              <dl className="facts">
                <dt>rating</dt>
                <dd className="mono">{num(data.rating)}</dd>
                <dt>charts scored</dt>
                <dd className="mono">{num(data.charts)}</dd>
                <dt>plays on the cabinet</dt>
                <dd className="mono">{num(data.plays)}</dd>
                {best ? (
                  <>
                    <dt>best single chart</dt>
                    <dd className="mono">
                      {best.title} · {best.rating}
                    </dd>
                  </>
                ) : null}
                <dt>last read</dt>
                <dd className="mono">{when(data.updatedAt)}</dd>
              </dl>
              <p className="hint">
                {panels.length > 1
                  ? "The tabs above are what this player chose to share. Anything not there was left private."
                  : "This player shares their rating only. Anything else was left private."}
              </p>
            </section>
          </>
        )}

        {panel === "best50" && data.best50 && (
          <div className="two-up wide-right">
            <Pool title="new version" rows={data.best50.new} size={15} />
            <Pool title="older versions" rows={data.best50.old} size={35} />
          </div>
        )}

        {panel === "traits" && (
          <section className="ledger">
            <div className="ledger-head">
              <Label>how they play</Label>
              <span className="mono hint">against their own curve</span>
            </div>
            <div className="two-up radar-split">
              <div className="radar-wrap">{wheel.length >= 3 ? <Radar axes={wheel} /> : null}</div>
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

        {panel === "recent" && data.recent && (
          <section className="ledger">
            <div className="ledger-head">
              <Label>recent plays</Label>
              <span className="mono hint">newest first</span>
            </div>
            {data.recent.length === 0 ? (
              <Empty>No plays recorded yet.</Empty>
            ) : (
              <table className="tbl compact">
                <tbody>
                  {data.recent.map((p, i) => (
                    <tr key={`${p.title}${p.day}${i}`}>
                      <td className="c-jacket">
                        <Jacket cover={p.cover} size={32} />
                      </td>
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

        {panel === "areas" && data.areas && (
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
    </Shell>
  );
}
