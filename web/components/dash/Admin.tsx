"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { ApiError, getJSON, type Overview } from "./api";
import { Empty, Label, num, when } from "./bits";
import { Frame } from "./Frame";

type Table = { name: string; bytes: number | null; rows?: number };
type AdminData = {
  accounts: { region: string; count: number; expired: number }[];
  expired: { userId: string; region: string; since: string }[];
  failingReads: { userId: string; lastRead: string; error: string }[];
  sources: { source: string; checkedAt: string; bytes: number; etag: boolean }[];
  busiest: { userId: string; plays: number }[];
  store: {
    bytes: number; freeBytes: number; walBytes: number; tables: Table[];
    plays: number; judgements: number; ratingPoints: number; playCounts: number; oldestPlay: string | null;
  };
  live: Record<string, number | boolean | number[] | undefined>;
  generatedAt: string;
};

function mb(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / 1048576).toFixed(2)} MB`;
}

function duration(seconds: number | undefined): string {
  if (!seconds && seconds !== 0) return "—";
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
  const scrapesBusy = Number(live.scrapesMax ?? 0) - Number(live.scrapesFree ?? 0);
  const rendersBusy = Number(live.rendersMax ?? 0) - Number(live.rendersFree ?? 0);
  return (
    <Frame user={me}>
      <main className="panel">
        <section className="ident">
          <div className="ident-who">
            <div className="label">developer · refreshed every 15s</div>
            <h1>Rasmai</h1>
            <div className="ident-sub mono">read at {when(data.generatedAt)}</div>
          </div>
        </section>

        <div className="two-up">
          <section className="ledger">
            <div className="ledger-head">
              <Label>process</Label>
              <span className="mono hint">{live.ready ? "connected" : "not ready"}</span>
            </div>
            <Facts
              rows={[
                ["uptime", duration(Number(live.uptimeSeconds))],
                ["servers", num(Number(live.guilds ?? 0))],
                ["shards", num(Number(live.shards ?? 1))],
                ["gateway latency", `${num(Number(live.latencyMs ?? 0))} ms`],
                ["charts indexed", num(Number(live.chartsIndexed ?? 0))],
                ["analyses in memory", `${num(Number(live.analysesCached ?? 0))} · ${num(Number(live.analysisTtlMinutes ?? 0))} min ttl`],
                ["reads in flight", `${scrapesBusy} / ${num(Number(live.scrapesMax ?? 0))}`],
                ["renders in flight", `${rendersBusy} / ${num(Number(live.rendersMax ?? 0))}`],
                ["site refreshes running", num(Number(live.refreshesRunning ?? 0))],
              ]}
            />
          </section>

          <section className="ledger">
            <div className="ledger-head">
              <Label>accounts · {linked}</Label>
              <span className="mono hint">{data.expired.length} need linking again</span>
            </div>
            <Facts
              rows={data.accounts.map((a) => [
                a.region.toUpperCase(),
                `${num(a.count)}${a.expired ? ` · ${a.expired} expired` : ""}`,
              ])}
            />
            <div className="ledger-head">
              <Label>stored</Label>
            </div>
            <Facts
              rows={[
                ["plays", num(data.store.plays)],
                ["judgement pages", num(data.store.judgements)],
                ["rating points", num(data.store.ratingPoints)],
                ["play counts", num(data.store.playCounts)],
                ["oldest play", data.store.oldestPlay ? data.store.oldestPlay.slice(0, 10) : "—"],
              ]}
            />
          </section>
        </div>

        <section className="ledger">
          <div className="ledger-head">
            <Label>database · {mb(data.store.bytes)}</Label>
            <span className="mono hint">
              {mb(data.store.freeBytes)} free{data.store.walBytes ? ` · ${mb(data.store.walBytes)} write-ahead log` : ""}
            </span>
          </div>
          <div className="scroll">
            <table className="tbl compact">
              <thead>
                <tr>
                  <th>Table</th>
                  <th className="c-num">Size</th>
                  <th className="c-num">Share</th>
                </tr>
              </thead>
              <tbody>
                {data.store.tables.map((t) => (
                  <tr key={t.name}>
                    <td className="mono">{t.name}</td>
                    <td className="c-num mono">{t.bytes === null ? `${num(t.rows ?? 0)} rows` : mb(t.bytes)}</td>
                    <td className="c-num">
                      {t.bytes === null ? (
                        <span className="dim">—</span>
                      ) : (
                        <span className="bar">
                          <span style={{ width: `${Math.min(100, (100 * t.bytes) / Math.max(1, data.store.bytes))}%` }} />
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <div className="two-up">
          <section className="ledger">
            <div className="ledger-head">
              <Label>source caches</Label>
              <span className="mono hint">shared by everyone, fixed cost</span>
            </div>
            {data.sources.length === 0 ? (
              <Empty>Nothing cached yet.</Empty>
            ) : (
              <table className="tbl compact">
                <tbody>
                  {data.sources.map((s) => (
                    <tr key={s.source}>
                      <td className="mono">{s.source}</td>
                      <td className="c-num mono dim">{mb(s.bytes)}</td>
                      <td className="c-num mono">{s.checkedAt ? when(s.checkedAt) : "never"}</td>
                      <td className="c-num mono dim">{s.etag ? "etag" : ""}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section className="ledger">
            <div className="ledger-head">
              <Label>needs attention</Label>
            </div>
            {data.expired.length === 0 && data.failingReads.length === 0 ? (
              <Empty>Every linked session is answering.</Empty>
            ) : (
              <table className="tbl compact">
                <tbody>
                  {data.expired.map((e) => (
                    <tr key={`x${e.userId}`}>
                      <td className="mono">{e.userId}</td>
                      <td className="mono dim">{e.region}</td>
                      <td className="c-num mono">session expired {when(e.since)}</td>
                    </tr>
                  ))}
                  {data.failingReads.map((r) => (
                    <tr key={`r${r.userId}`}>
                      <td className="mono">{r.userId}</td>
                      <td className="mono dim">daily read</td>
                      <td className="c-num mono">{r.error}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="ledger-head">
              <Label>busiest accounts</Label>
            </div>
            <table className="tbl compact">
              <tbody>
                {data.busiest.map((b) => (
                  <tr key={b.userId}>
                    <td className="mono">{b.userId}</td>
                    <td className="c-num mono">{num(b.plays)} plays</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      </main>
    </Frame>
  );
}
