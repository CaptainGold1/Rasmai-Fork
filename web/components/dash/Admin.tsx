"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { ApiError, getJSON, type Overview } from "./api";
import { Empty, Label, num, when } from "./bits";
import { Frame } from "./Frame";

type Person = { name?: string; handle?: string; avatar?: string };
type Table = { name: string; bytes: number | null; rows?: number };
type AdminData = {
  accounts: { region: string; count: number; expired: number }[];
  expired: ({ userId: string; region: string; since: string } & Person)[];
  failingReads: ({ userId: string; lastRead: string; error: string } & Person)[];
  sources: { source: string; checkedAt: string; bytes: number; etag: boolean }[];
  busiest: ({ userId: string; plays: number } & Person)[];
  activity: { day: string; plays: number; people: number }[];
  growth: { day: string; accounts: number }[];
  store: {
    bytes: number; freeBytes: number; walBytes: number; tables: Table[];
    plays: number; judgements: number; ratingPoints: number; playCounts: number; oldestPlay: string | null;
  };
  live: Record<string, number | boolean | number[] | undefined>;
  generatedAt: string;
};

const SLICES = ["#ff3d8f", "#5cd3e8", "#f0c04a", "#8f7dff", "#4fd18b", "#ff9f5c", "#9aa0b5"];

function size(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1048576) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(2)} MB`;
}

function duration(seconds: number | undefined): string {
  if (seconds === undefined || Number.isNaN(seconds)) return "—";
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  return d ? `${d}d ${h}h` : h ? `${h}h ${m}m` : `${m}m`;
}

function Facts({ rows }: { rows: [string, React.ReactNode][] }) {
  return (
    <dl className="facts">
      {rows.map(([key, value]) => (
        <Fragment key={key}>
          <dt>{key}</dt>
          <dd className="mono">{value}</dd>
        </Fragment>
      ))}
    </dl>
  );
}

/** A limit and how much of it is in use, as a filled track. */
function Gauge({ label, used, total }: { label: string; used: number; total: number }) {
  const share = total > 0 ? Math.min(100, (100 * used) / total) : 0;
  return (
    <div className="gauge">
      <span className="gauge-top">
        <span>{label}</span>
        <span className="mono">
          {num(used)} <span className="dim">/ {num(total)}</span>
        </span>
      </span>
      <span className="bar">
        <span style={{ width: `${Math.max(share, used > 0 ? 4 : 0)}%` }} />
      </span>
    </div>
  );
}

/** Plays per day over the last month, with the days nobody played left empty. */
function Activity({ days }: { days: AdminData["activity"] }) {
  const peak = Math.max(1, ...days.map((d) => d.plays));
  const total = days.reduce((sum, d) => sum + d.plays, 0);
  return (
    <>
      <div className="admin-bars" role="img" aria-label={`${total} plays recorded over the last 30 days`}>
        {days.map((d) => (
          <span key={d.day} className={`admin-bar${d.plays ? "" : " empty"}`} title={`${d.day}: ${d.plays} plays, ${d.people} accounts`}>
            <span style={{ height: `${d.plays ? Math.max(3, (100 * d.plays) / peak) : 2}%` }} />
          </span>
        ))}
      </div>
      <div className="admin-axis mono">
        <span>{days[0]?.day.slice(5)}</span>
        <span className="dim">peak {num(peak)} in a day</span>
        <span>{days[days.length - 1]?.day.slice(5)}</span>
      </div>
    </>
  );
}

/** What fills the database, as one stacked bar plus its key. */
function Composition({ tables, total }: { tables: Table[]; total: number }) {
  const sized = tables.filter((t) => t.bytes !== null) as { name: string; bytes: number }[];
  if (!sized.length) return null;
  const top = sized.slice(0, 6);
  const rest = sized.slice(6).reduce((sum, t) => sum + t.bytes, 0);
  const parts = rest > 0 ? [...top, { name: "everything else", bytes: rest }] : top;
  return (
    <>
      <div className="stack" role="img" aria-label="what fills the database">
        {parts.map((t, i) => (
          <span
            key={t.name}
            title={`${t.name}: ${size(t.bytes)}`}
            style={{ width: `${(100 * t.bytes) / Math.max(1, total)}%`, background: SLICES[i % SLICES.length] }}
          />
        ))}
      </div>
      <ul className="keys">
        {parts.map((t, i) => (
          <li key={t.name}>
            <i style={{ background: SLICES[i % SLICES.length] }} />
            <span className="mono">{t.name}</span>
            <b className="mono">{size(t.bytes)}</b>
          </li>
        ))}
      </ul>
    </>
  );
}

function Who({ person, id }: { person: Person; id: string }) {
  return (
    <span className="who">
      {person.avatar ? <img src={person.avatar} alt="" width={26} height={26} loading="lazy" /> : <span className="who-blank" />}
      <span className="who-text">
        <b>{person.name || id}</b>
        <span className="mono dim">{person.handle ? `@${person.handle}` : id}</span>
      </span>
    </span>
  );
}

export function Admin() {
  const [data, setData] = useState<AdminData | null>(null);
  const [error, setError] = useState("");
  const [me, setMe] = useState<Overview["user"] | undefined>();

  const load = useCallback(() => {
    getJSON<AdminData>("/api/me/admin")
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: ApiError) => setError(e.status === 404 ? "no such page" : e.message));
  }, []);

  useEffect(() => {
    getJSON<Overview>("/api/me").then((d) => setMe(d.user)).catch(() => undefined);
    load();
    const timer = setInterval(load, 15000);
    return () => clearInterval(timer);
  }, [load]);

  // the route answers 404 to everyone but the one account, so the page says the same rather than hinting
  if (error) {
    return (
      <Frame user={me}>
        <div className="gate">
          <h1>
            Nothing <em>here</em>.
          </h1>
          <p className="lede">This page does not exist.</p>
          <a className="button" href="/me/">
            back to your dashboard →
          </a>
        </div>
      </Frame>
    );
  }
  if (!data) {
    return (
      <Frame user={me}>
        <div className="gate">
          <p className="hint">Loading…</p>
        </div>
      </Frame>
    );
  }

  const live = data.live;
  const linked = data.accounts.reduce((sum, a) => sum + a.count, 0);
  const n = (key: string) => Number(live[key] ?? 0);
  const month = data.activity.reduce((sum, d) => sum + d.plays, 0);
  const attention = data.expired.length + data.failingReads.length;
  return (
    <Frame user={me}>
      <main className="panel admin">
        <section className="ident">
          <div className="ident-who">
            <div className="label">developer</div>
            <h1>Rasmai</h1>
            <div className="ident-sub mono">
              {live.ready ? "connected" : "not ready"} · up {duration(n("uptimeSeconds"))} · read {when(data.generatedAt)}
            </div>
          </div>
          <div className="readout big">
            <span className="lbl">accounts</span>
            <span className="val">{num(linked)}</span>
            <span className="lbl">plays stored</span>
            <span className="val">{num(data.store.plays)}</span>
            <span className="lbl">database</span>
            <span className="val">{size(data.store.bytes)}</span>
          </div>
        </section>

        <section className="ledger">
          <div className="ledger-head">
            <Label>plays recorded · last 30 days</Label>
            <span className="mono hint">{num(month)} plays</span>
          </div>
          <Activity days={data.activity} />
        </section>

        <div className="two-up">
          <section className="ledger">
            <div className="ledger-head">
              <Label>load right now</Label>
              <span className="mono hint">{num(n("latencyMs"))} ms to the gateway</span>
            </div>
            <Gauge label="score reads in flight" used={n("scrapesMax") - n("scrapesFree")} total={n("scrapesMax")} />
            <Gauge label="image renders in flight" used={n("rendersMax") - n("rendersFree")} total={n("rendersMax")} />
            <Gauge label="analyses held in memory" used={n("analysesCached")} total={Math.max(n("analysesCached"), 20)} />
            <Facts
              rows={[
                ["servers", `${num(n("guilds"))} over ${num(n("shards") || 1)} shard${n("shards") === 1 ? "" : "s"}`],
                ["charts indexed", num(n("chartsIndexed"))],
                ["analysis lifetime", `${num(n("analysisTtlMinutes"))} min`],
                ["site reads running", num(n("refreshesRunning"))],
              ]}
            />
          </section>

          <section className="ledger">
            <div className="ledger-head">
              <Label>what is stored</Label>
              <span className="mono hint">
                {data.store.oldestPlay ? `since ${data.store.oldestPlay.slice(0, 10)}` : "nothing yet"}
              </span>
            </div>
            <Facts
              rows={[
                ["linked accounts", data.accounts.map((a) => `${num(a.count)} ${a.region.toUpperCase()}`).join(" · ") || "—"],
                ["plays", num(data.store.plays)],
                ["judgement pages", num(data.store.judgements)],
                ["rating points", num(data.store.ratingPoints)],
                ["play counts", num(data.store.playCounts)],
                ["free space in the file", size(data.store.freeBytes)],
                ["write-ahead log", data.store.walBytes ? size(data.store.walBytes) : "checkpointed"],
              ]}
            />
          </section>
        </div>

        <section className="ledger">
          <div className="ledger-head">
            <Label>what fills the database · {size(data.store.bytes)}</Label>
            <span className="mono hint">{size(data.store.freeBytes)} free</span>
          </div>
          <Composition tables={data.store.tables} total={data.store.bytes} />
        </section>

        <div className="two-up">
          <section className="ledger">
            <div className="ledger-head">
              <Label>busiest accounts</Label>
              <span className="mono hint">by plays recorded</span>
            </div>
            {data.busiest.length === 0 ? (
              <Empty>No plays recorded yet.</Empty>
            ) : (
              <ul className="people">
                {data.busiest.map((b) => (
                  <li key={b.userId}>
                    <Who person={b} id={b.userId} />
                    <span className="mono">{num(b.plays)} plays</span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section className="ledger">
            <div className="ledger-head">
              <Label>needs attention</Label>
              <span className={`mono hint${attention ? " bad" : ""}`}>{attention ? `${attention} to look at` : "all clear"}</span>
            </div>
            {attention === 0 ? (
              <Empty>Every linked session is answering and the daily reads are landing.</Empty>
            ) : (
              <ul className="people">
                {data.expired.map((e) => (
                  <li key={`x${e.userId}`}>
                    <Who person={e} id={e.userId} />
                    <span className="mono bad">expired {when(e.since)}</span>
                  </li>
                ))}
                {data.failingReads.map((r) => (
                  <li key={`r${r.userId}`}>
                    <Who person={r} id={r.userId} />
                    <span className="mono bad">{r.error}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        <section className="ledger">
          <div className="ledger-head">
            <Label>source caches</Label>
            <span className="mono hint">shared by everyone, and the same size whoever is linked</span>
          </div>
          {data.sources.length === 0 ? (
            <Empty>Nothing cached yet.</Empty>
          ) : (
            <div className="scroll">
              <table className="tbl compact keep">
                <thead>
                  <tr>
                    <th>Source</th>
                    <th className="c-num">Size</th>
                    <th className="c-num">Last checked</th>
                    <th>Conditional</th>
                  </tr>
                </thead>
                <tbody>
                  {data.sources.map((s) => (
                    <tr key={s.source}>
                      <td className="mono strong">{s.source}</td>
                      <td className="c-num mono">{size(s.bytes)}</td>
                      <td className="c-num mono dim">{s.checkedAt ? when(s.checkedAt) : "never"}</td>
                      <td className="mono dim">{s.etag ? "etag" : "full fetch"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      </main>
    </Frame>
  );
}
