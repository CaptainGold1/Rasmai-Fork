"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Turnstile } from "@/components/Turnstile";
import { InstallHint } from "@/components/Pwa";
import { ApiError, SIGNED_OUT_EVENT, getJSON, postJSON, type ChartRow, type LookupTarget, type Overview, type RecentPlay, type RefreshStatus } from "./api";
import { Lookup } from "./Lookup";
import { Ago, Empty, LoadError, day, num, type OpenChart } from "./bits";
import { Areas } from "./Areas";
import { JudgementProfile, Traits } from "./Traits";
import { Charts } from "./Charts";
import { NewCharts } from "./NewCharts";
import { Picks } from "./Picks";
import { Account } from "./Account";
import { AdminPanel } from "./Admin";
import { Best50 } from "./Best50";
import { Frame } from "./Frame";
import { OverviewTab } from "./OverviewTab";
import { Recent } from "./Recent";
import { type Tab, TABS, Tabs, RefreshBar, tabsFor } from "./Tabs";
import { SaveImage, type ImageKind } from "./bits";

// the tabs the bot already draws a picture of, and which of its commands draws it
const IMAGE_FOR: Partial<Record<Tab, ImageKind[]>> = {
  overview: ["profile", "progress"],
  picks: ["analyze"],
  new: ["new"],
  traits: ["traits"],
  best50: ["best50"],
  recent: ["recent"],
};

export function Dash() {
  const [me, setMe] = useState<Overview | null>(null);
  const [signedOut, setSignedOut] = useState(false);
  const [oauth, setOauth] = useState(true);
  const [turnstile, setTurnstile] = useState("");
  const [human, setHuman] = useState("");
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("overview");
  const [charts, setCharts] = useState<ChartRow[] | null>(null);
  const [chartsError, setChartsError] = useState("");
  const [recent, setRecent] = useState<RecentPlay[] | null>(null);
  const [recentError, setRecentError] = useState("");
  const [refresh, setRefresh] = useState<RefreshStatus | null>(null);
  const [lookup, setLookup] = useState<LookupTarget | null>(null);
  const [areaFocus, setAreaFocus] = useState("");
  // tabs stay mounted once opened, so filters, paging and fetched data survive a trip to another tab
  const [visited, setVisited] = useState<Set<Tab>>(() => new Set(["overview"]));
  const pollFailures = useRef(0);

  const load = useCallback(() => {
    getJSON<Overview>("/api/me")
      .then((data) => {
        setMe(data);
        setSignedOut(false);
        setRefresh(data.refresh ?? null);
      })
      .catch((e: ApiError) => {
        if (e.status === 401) {
          setSignedOut(true);
          setOauth(Boolean(e.body?.oauth));
          setTurnstile(String(e.body?.turnstile ?? ""));
        } else setError(e.message);
      });
  }, []);

  // any API call that answers 401 sends the dashboard back to the sign-in gate, whichever tab made it
  useEffect(() => {
    const onSignedOut = (event: Event) => {
      const body = ((event as CustomEvent).detail ?? {}) as Record<string, unknown>;
      setSignedOut(true);
      if ("oauth" in body) setOauth(Boolean(body.oauth));
      if ("turnstile" in body) setTurnstile(String(body.turnstile ?? ""));
    };
    window.addEventListener(SIGNED_OUT_EVENT, onSignedOut);
    return () => window.removeEventListener(SIGNED_OUT_EVENT, onSignedOut);
  }, []);

  // the address carries the tab and the chart on show, so Back and Forward move between them
  const applyLocation = useCallback(() => {
    const params = new URLSearchParams(window.location.search);
    const hash = window.location.hash.replace("#", "") as Tab;
    const wanted = params.get("chart");
    const cover = params.get("cover");
    if (wanted || cover) {
      setLookup({ title: wanted ?? "", cover: cover ?? undefined, type: params.get("type") ?? undefined, difficulty: params.get("difficulty") ?? undefined });
      setTab("chart");
      setVisited((v) => new Set(v).add("chart"));
      return;
    }
    const area = params.get("area");
    if (area) {
      setAreaFocus(area);
      setTab("areas");
      setVisited((v) => new Set(v).add("areas"));
      return;
    }
    const next: Tab = tabsFor(true).some((t) => t.key === hash) ? hash : "overview";
    setTab(next);
    setVisited((v) => new Set(v).add(next));
  }, []);

  useEffect(() => {
    window.addEventListener("popstate", applyLocation);
    return () => window.removeEventListener("popstate", applyLocation);
  }, [applyLocation]);

  useEffect(() => {
    load();
    const params = new URLSearchParams(window.location.search);
    const kind = params.get("error");
    if (kind === "discord") setError("Discord did not confirm the sign-in. Try again.");
    if (kind === "state") setError("That sign-in link was stale. Try again.");
    if (kind === "oauth_unconfigured") setError("Sign-in is not set up on this server yet.");
    if (kind === "verify") setError("The human check did not pass. Try again.");
    applyLocation();
  }, [load, applyLocation]);

  const loadCharts = useCallback(() => {
    setChartsError("");
    getJSON<{ charts: ChartRow[] }>("/api/me/charts")
      .then((d) => setCharts(d.charts))
      .catch((e: ApiError) => setChartsError(e.message));
  }, []);
  useEffect(() => {
    if (!me?.linked || charts !== null || chartsError) return;
    loadCharts();
  }, [me, charts, chartsError, loadCharts]);

  const loadRecent = useCallback(() => {
    setRecentError("");
    getJSON<{ plays: RecentPlay[] }>("/api/me/recent")
      .then((d) => setRecent(d.plays))
      .catch((e: ApiError) => setRecentError(e.message));
  }, []);
  useEffect(() => {
    if (tab !== "recent" || !me?.linked || recent !== null || recentError) return;
    loadRecent();
  }, [tab, me, recent, recentError, loadRecent]);

  // follow a running refresh, then reload everything once it lands; a bot that stops answering ends the wait
  useEffect(() => {
    if (!refresh?.running) return;
    pollFailures.current = 0;
    const timer = setInterval(() => {
      getJSON<RefreshStatus>("/api/me/refresh")
        .then((s) => {
          pollFailures.current = 0;
          setRefresh(s);
          if (!s.running) {
            setCharts(null);
            setRecent(null);
            load();
          }
        })
        .catch((e: ApiError) => {
          pollFailures.current += 1;
          if (pollFailures.current >= 5 || e.status === 401) {
            setRefresh({ running: false, stage: "failed", error: "lost contact with the bot while it was reading. Reload the page, or try again in a minute." });
          }
        });
    }, 1500);
    return () => clearInterval(timer);
  }, [refresh, load]);

  const show = (t: Tab) => {
    setTab(t);
    setVisited((v) => (v.has(t) ? v : new Set(v).add(t)));
    if (t !== tab) window.scrollTo({ top: 0 });
  };
  // the chart tab's address names the chart on show, and only that: an area link's query must not ride along
  const chartAddress = (target: LookupTarget) => {
    const params = new URLSearchParams(target.cover ? { cover: target.cover } : { chart: target.title });
    if (target.type) params.set("type", target.type);
    if (target.difficulty) params.set("difficulty", target.difficulty);
    return `${window.location.pathname}?${params}#chart`;
  };
  const pick = (t: Tab) => {
    if (t === tab) return;
    show(t);
    window.history.pushState(null, "", t === "chart" && lookup ? chartAddress(lookup) : `${window.location.pathname}#${t}`);
  };
  const openChart: OpenChart = (title, type, difficulty) => {
    setLookup({ title, type, difficulty });
    show("chart");
    window.history.pushState(null, "", `${window.location.pathname}?chart=${encodeURIComponent(title)}&type=${type}&difficulty=${difficulty}#chart`);
  };
  const signOut = () => postJSON("/auth/logout").then(() => window.location.assign("/"));

  if (signedOut) {
    return (
      <Frame>
        <div className="gate">
          <h1>
            Your scores, <em>on the web</em>.
          </h1>
          <p className="lede">
            Everything the bot has read from your maimai account: what to play next, your best 50, every chart, your rating over time.
            Sign in with the Discord account you use the bot with.
          </p>
          {oauth && turnstile ? (
            <form method="post" action="/auth/discord" className="signin">
              <Turnstile siteKey={turnstile} action="dashboard" onToken={setHuman} onError={() => setError("The human check could not load. Reload the page.")} />
              <input type="hidden" name="cf-turnstile-response" value={human} />
              <button className="button pink" type="submit" disabled={!human}>
                sign in with Discord
              </button>
            </form>
          ) : oauth ? (
            <a className="button pink" href="/auth/discord">
              sign in with Discord
            </a>
          ) : (
            <p className="hint">Sign-in is not set up on this server yet. The owner needs to add a Discord client id and secret.</p>
          )}
          {error && <p className="hint">{error}</p>}
          <div className="aside">Only your Discord id and name are read. Nothing is posted, and no server list is requested.</div>
          <InstallHint />
        </div>
      </Frame>
    );
  }
  if (!me) {
    return (
      <Frame>
        <div className="gate">{error ? <p className="hint">{error}</p> : <p className="hint">Loading…</p>}</div>
      </Frame>
    );
  }
  if (!me.linked) {
    return (
      <Frame user={me.user} onSignOut={signOut}>
        <div className="gate">
          <h1>
            No maimai account <em>linked yet</em>.
          </h1>
          <p className="lede">
            This Discord account is signed in, but the bot has no maimai session for it. Run <code>/login</code> in Discord and follow the
            link it gives you; come back here afterwards.
          </p>
          <a className="button" href="/">
            how linking works →
          </a>
        </div>
      </Frame>
    );
  }

  const p = me.profile!;
  const s = me.snapshot!;
  return (
    <Frame user={me.user} onSignOut={signOut}>
      {me.sessionExpired ? <SessionExpired since={me.sessionExpired} /> : null}
      <section className="ident">
        <div className="ident-who">
          <div className="label">
            {me.region?.toUpperCase()} · <Ago iso={p.updatedAt} prefix="updated " />
          </div>
          <h1>{p.name || "—"}</h1>
          <div className="ident-sub mono">
            {[...new Set([p.dan, p.title].filter(Boolean))].join(" · ") || "no title read yet"} · {num(p.totalPlayCount)} plays
          </div>
          {me.sinceLast && (me.sinceLast.plays > 0 || me.sinceLast.ratingDelta !== 0) && (
            <div className="since mono">
              since {day(me.sinceLast.since)}: {me.sinceLast.ratingDelta ? `rating ${me.sinceLast.ratingDelta > 0 ? "+" : ""}${me.sinceLast.ratingDelta}` : "rating unchanged"}
              {me.sinceLast.plays ? ` · ${num(me.sinceLast.plays)} play${me.sinceLast.plays === 1 ? "" : "s"}` : ""}
              {me.sinceLast.newBests ? ` · ${me.sinceLast.newBests} new best${me.sinceLast.newBests === 1 ? "" : "s"}` : ""}
            </div>
          )}
        </div>
        <div className="readout big">
          <span className="lbl">rating</span>
          <span className="val">{num(p.rating)}</span>
          <span className="lbl">best 50</span>
          <span className="val">{num(s.best50)}</span>
          <span className="lbl">new · old</span>
          <span className="val pair">
            <span>{num(s.newTotal)}</span>
            <span className="sep">·</span>
            <span>{num(s.oldTotal)}</span>
          </span>
        </div>
      </section>

      <Tabs current={tab} onPick={pick} admin={me.admin} />

      {IMAGE_FOR[tab] && (
        <div className="tab-tools">
          {IMAGE_FOR[tab]!.map((kind) => (
            <SaveImage key={kind} kind={kind} />
          ))}
        </div>
      )}

      {refresh?.running && <RefreshBar status={refresh} />}

      <main className="panel">
        <div hidden={tab !== "overview"}>
          <OverviewTab me={me} charts={charts} chartsError={chartsError} onRetry={loadCharts} />
        </div>
        {visited.has("picks") && (
          <div hidden={tab !== "picks"}>
            <Picks initial={String(me.settings?.challenge ?? "balanced")} onOpen={openChart} />
          </div>
        )}
        {visited.has("new") && (
          <div hidden={tab !== "new"}>
            <NewCharts
              initialChallenge={String(me.settings?.challenge ?? "balanced")}
              initialDifficulty={String(me.settings?.new_difficulty ?? "any")}
              onOpen={openChart}
            />
          </div>
        )}
        {visited.has("best50") && (
          <div hidden={tab !== "best50"}>
            {chartsError ? <LoadError what="your charts" message={chartsError} onRetry={loadCharts} /> : <Best50 charts={charts} cutoffs={me.analysis?.best50} onOpen={openChart} />}
          </div>
        )}
        {visited.has("charts") && (
          <div hidden={tab !== "charts"}>
            {chartsError ? <LoadError what="your charts" message={chartsError} onRetry={loadCharts} /> : charts ? <Charts rows={charts} onOpen={openChart} /> : <Empty>Loading charts…</Empty>}
          </div>
        )}
        {visited.has("chart") && (
          <div hidden={tab !== "chart"}>
            <Lookup target={lookup} />
          </div>
        )}
        {visited.has("recent") && (
          <div hidden={tab !== "recent"}>
            {recentError ? <LoadError what="your play history" message={recentError} onRetry={loadRecent} /> : <Recent plays={recent} total={me.playHistory ?? 0} onOpen={openChart} />}
          </div>
        )}
        {visited.has("traits") && (
          <div hidden={tab !== "traits"}>
            <Traits
              traits={me.analysis?.profile?.traits ?? []}
              axes={me.analysis?.profile?.traitAxes ?? []}
              families={me.analysis?.profile?.traitFamilies ?? []}
              charts={Number(me.analysis?.profile?.sampleSize ?? 0)}
              practice={me.analysis?.traitPractice ?? []}
              onOpen={openChart}
            />
            <JudgementProfile data={me.judgements ?? null} />
          </div>
        )}
        {visited.has("areas") && (
          <div hidden={tab !== "areas"}>
            <Areas key={me.profile?.updatedAt ?? ""} focus={areaFocus} />
          </div>
        )}
        {visited.has("account") && (
          <div hidden={tab !== "account"}>
            <Account me={me} refresh={refresh} onRefresh={(st) => setRefresh(st)} />
          </div>
        )}
        {me.admin && visited.has("admin") && (
          <div hidden={tab !== "admin"}>
            <AdminPanel />
          </div>
        )}
      </main>
    </Frame>
  );
}

/** Shown above everything when maimai DX NET has refused the saved sign-in: reads stop until it is linked again. */
function SessionExpired({ since }: { since: string }) {
  const when = new Date(since);
  const on = Number.isNaN(when.getTime())
    ? ""
    : ` on ${when.toLocaleDateString(undefined, { day: "numeric", month: "short" })}`;
  return (
    <aside className="expired" role="status">
      <b>Your maimai session has expired.</b> maimai DX NET stopped accepting the saved sign-in{on}, so your scores are no
      longer being read. Everything below is your last successful read. Run <code>/login</code> in Discord to link again and
      the reads carry on from where they stopped.
    </aside>
  );
}
