import { useEffect, useState } from "react";
import { getJSON, type Picks as PicksData } from "./api";
import { Chip, Empty, Jacket, Label, LoadError, num, pct } from "./bits";
import { TitleLink, type OpenChart } from "./bits";

const LEVELS: { key: string; label: string; note: string }[] = [
  { key: "easy", label: "Easier", note: "the surest step, about a coin flip" },
  { key: "balanced", label: "Balanced", note: "best expected gain, one in four" },
  { key: "hard", label: "Challenging", note: "a stretch, about one in six" },
  { key: "extreme", label: "Long shots", note: "the biggest gain on the board, about one in ten" },
];

const CHART_LEVELS = ["15", "14+", "14", "13+", "13", "12+", "12", "11+", "11", "10+", "10", "9+", "9", "8+", "8", "7+", "7"];
/** A level (13+), one constant (13.2) or a range (13.0-13.4); the server reads the same forms. */
const SCOPE_OK = /^(\d{1,2}\+?|\d{1,2}\.\d|\d{1,2}(\.\d)?\s*-\s*\d{1,2}(\.\d)?)$/;

export function Picks({ initial, onOpen }: { initial: string; onOpen?: OpenChart }) {
  const [challenge, setChallenge] = useState(LEVELS.some((l) => l.key === initial) ? initial : "balanced");
  const [chartLevel, setChartLevel] = useState("");
  const [constant, setConstant] = useState("");
  const [data, setData] = useState<Record<string, PicksData>>({});
  const [error, setError] = useState("");
  const typed = constant.trim();
  const scope = typed || chartLevel;
  const scopeOk = !scope || SCOPE_OK.test(scope);
  const key = `${challenge}|${scopeOk ? scope : ""}`;
  const picks = scopeOk ? data[key] : undefined;     // a half-typed constant shows the hint, not the unfiltered list

  useEffect(() => {
    if (data[key] || error || !scopeOk) return;
    const query = new URLSearchParams({ challenge });
    if (scope) query.set("level", scope);
    getJSON<PicksData>(`/api/me/picks?${query}`)
      .then((d) => setData((prev) => ({ ...prev, [key]: d })))
      .catch((e: Error) => setError(e.message));
  }, [key, challenge, scope, scopeOk, data, error]);

  const level = LEVELS.find((l) => l.key === challenge)!;
  return (
    <>
      <div className="row-between">
        <div className="seg" role="group" aria-label="How far above your usual scores the targets sit">
          {LEVELS.map((l) => (
            <button key={l.key} type="button" className={l.key === challenge ? "on" : ""} aria-pressed={l.key === challenge} onClick={() => setChallenge(l.key)}>
              {l.label}
            </button>
          ))}
        </div>
        <span className="hint">
          {level.note}
          {picks?.scope ? ` · picks and new charts held to ${picks.scope}; the road is the whole route` : ""}
        </span>
      </div>
      <div className="filters scope-filters">
        <select value={chartLevel} onChange={(e) => setChartLevel(e.target.value)} aria-label="Only this level" disabled={Boolean(typed)}>
          <option value="">any level</option>
          {CHART_LEVELS.map((l) => (
            <option key={l} value={l}>
              level {l}
            </option>
          ))}
        </select>
        <input
          className="search scope-constant"
          type="text"
          role="searchbox"
          value={constant}
          placeholder="or a constant: 13.2, or 13.0-13.4"
          aria-label="Only this constant or range"
          onChange={(e) => setConstant(e.target.value)}
        />
        {!scopeOk && <span className="hint">Use a level like 13+, a constant like 13.2, or a range like 13.0-13.4.</span>}
      </div>
      {error && <LoadError what="the picks" message={error} onRetry={() => setError("")} />}
      {!picks && !error && scopeOk && <Empty>Working out what to play…</Empty>}
      {picks && picks.recommendations.length === 0 && (
        <Empty>Nothing at {picks.scope || "this level"} moves your best-50 at the {level.label.toLowerCase()} level. Try a bolder level, a wider range, or clear the filter.</Empty>
      )}
      {picks && picks.recommendations.length > 0 && <PickTables picks={picks} onOpen={onOpen} />}
    </>
  );
}

function PickTables({ picks, onOpen }: { picks: PicksData; onOpen?: OpenChart }) {
  const movers = picks.recommendations.filter((r) => r.category !== "near" && r.category !== "try");
  const tries = picks.recommendations.filter((r) => r.category === "try");
  const near = picks.recommendations.filter((r) => r.category === "near");
  const gain = picks.summary?.reachableGain ?? movers.reduce((s, r) => s + r.potential_gain, 0);
  return (
    <>
      {picks.summary?.fallbackFrom && (
        <p className="hint">Nothing at the {picks.summary.fallbackFrom} level moves your best-50 yet, so these are the balanced picks.</p>
      )}
      <section className="ledger">
        <div className="ledger-head">
          <Label info="Played charts where a better score adds the most to your best 50. Now is your score, Target is the score the model gives you a fair chance at, and Gain is what reaching it adds to your rating.">
            grind these · {movers.length} charts · <b className="gold">+{gain}</b> if every target lands
          </Label>
        </div>
        {movers.length === 0 ? (
          <Empty>No played chart moves your best-50 at this level. Try a different level, or the new charts below.</Empty>
        ) : (
          <div className="scroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="c-n">#</th>
                <th colSpan={2}>Chart</th>
                <th className="c-num">Now</th>
                <th className="c-num">Target</th>
                <th>Rank</th>
                <th className="c-num">Odds</th>
                <th className="c-num">Plays</th>
                <th className="c-num">Gain</th>
              </tr>
            </thead>
            <tbody>
              {movers.map((r, i) => (
                <tr key={`${r.song}|${r.chart_type}|${r.difficulty_type}`}>
                  <td className="c-n">{i + 1}</td>
                  <td className="c-jacket">
                    <Jacket cover={r.cover_url} />
                  </td>
                  <td className="c-title">
                    <TitleLink title={r.song} type={r.chart_type} difficulty={r.difficulty_type} onOpen={onOpen} />
                    <Chip difficulty={r.difficulty_type} level={r.level} constant={r.difficulty} type={r.chart_type} />
                    <span className="sub">
                      {r.estimated ? "not in the chart database yet · constant estimated from its level · " : ""}
                      {r.is_unplayed ? `never played · a first pass should land ~${r.expected.toFixed(1)}%` : `you usually score ~${r.expected.toFixed(1)}% here`}
                      {r.value_chart_reason?.includes("one run") ? " · your one run here ended far under that, so it is read as a run that was dropped" : ""}
                    </span>
                  </td>
                  <td className="c-num mono" data-l="now">{r.is_unplayed ? <span className="dim">new</span> : pct(r.current_accuracy)}</td>
                  <td className="c-num mono strong" data-l="target">{pct(r.target_accuracy)}</td>
                  <td className="mono" data-l="rank">
                    {r.is_unplayed ? <b>{r.target_rank}</b> : <>{r.current_rank} → <b>{r.target_rank}</b></>}
                  </td>
                  <td className="c-num mono" data-l="odds">{Math.round(r.feasibility * 100)}%</td>
                  <td className="c-num mono dim" data-l="plays">{r.plays > 0 ? r.plays : "?"}</td>
                  <td className="c-num mono gain" data-l="gain">+{r.potential_gain}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </section>

      {tries.length > 0 && (
        <section className="ledger">
          <div className="ledger-head">
            <Label info="Charts you have never played, offered because the grind list is short. Some would bank rating on a good first run; the rest carry a pattern your own scores say costs you points, so they are worth a run as practice.">
              worth a first run · {tries.length} charts
            </Label>
          </div>
          <table className="tbl compact">
            <tbody>
              {tries.map((r) => (
                <tr key={`${r.song}|${r.chart_type}|${r.difficulty_type}`}>
                  <td className="c-jacket">
                    <Jacket cover={r.cover_url} size={32} />
                  </td>
                  <td className="c-title">
                    <TitleLink title={r.song} type={r.chart_type} difficulty={r.difficulty_type} onOpen={onOpen} />
                    <Chip difficulty={r.difficulty_type} level={r.level} constant={r.difficulty} type={r.chart_type} />
                    <span className="sub">{(r.value_chart_reason ?? "").replace("never played · ", "")}</span>
                  </td>
                  <td className="c-num mono strong" data-l="aim for">{pct(r.target_accuracy)}</td>
                  <td className="c-num mono" data-l="odds">{Math.round(r.feasibility * 100)}%</td>
                  <td className="c-num mono gain" data-l="gain">{r.potential_gain > 0 ? `+${r.potential_gain}` : <span className="dim">banks</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}

      <section className="ledger">
        <div className="ledger-head">
          <Label info="A route to the next rating milestone: the targets that, taken together, cover the points needed. The percentage is how far above your usual score they ask you to go, so a small number is a gentle route.">road to {num(picks.plan.goal)}</Label>
          <span className="mono hint">
            {picks.plan.reached
              ? `covers the full +${picks.plan.needed}`
              : `+${picks.plan.total} of the +${picks.plan.needed} needed · ${picks.plan.shortfall} short`}
            {" · "}
            {picks.plan.averageStretch >= 0 ? "+" : ""}
            {picks.plan.averageStretch.toFixed(1)}% above your usual score
          </span>
        </div>
        {picks.plan.steps.length === 0 ? (
          <Empty>No route yet at this level.</Empty>
        ) : (
          <div className="scroll">
          <table className="tbl">
            <thead>
              <tr>
                <th className="c-n">#</th>
                <th colSpan={2}>Chart</th>
                <th className="c-num">Now</th>
                <th className="c-num">Target</th>
                <th>Rank</th>
                <th className="c-num">Odds</th>
                <th className="c-num">Gain</th>
                <th className="c-num">Total</th>
              </tr>
            </thead>
            <tbody>
              {picks.plan.steps.map((s, i) => (
                <tr key={`${s.option.title}|${s.option.chart_type}|${s.option.difficulty_type}`}>
                  <td className="c-n">{i + 1}</td>
                  <td className="c-jacket">
                    <Jacket cover={s.option.cover} />
                  </td>
                  <td className="c-title">
                    <TitleLink title={s.option.title} type={s.option.chart_type} difficulty={s.option.difficulty_type} onOpen={onOpen} />
                    <Chip difficulty={s.option.difficulty_type} level={s.option.level} constant={s.option.constant} type={s.option.chart_type} />
                    <span className="sub">{s.option.is_unplayed ? "never played" : s.option.plays > 0 ? `${s.option.plays} plays` : "plays unknown"}</span>
                  </td>
                  <td className="c-num mono" data-l="now">{s.option.is_unplayed ? "—" : pct(s.option.current_accuracy)}</td>
                  <td className="c-num mono strong" data-l="target">{pct(s.option.target_accuracy)}</td>
                  <td className="mono" data-l="rank">
                    {s.option.current_rank} → <b>{s.option.target_rank}</b>
                  </td>
                  <td className="c-num mono" data-l="odds">{Math.round(s.option.feasibility * 100)}%</td>
                  <td className="c-num mono gain" data-l="gain">+{s.gain}</td>
                  <td className="c-num mono dim" data-l="total">{s.cumulative}</td>
                </tr>
              ))}
            </tbody>
          </table>
          </div>
        )}
      </section>

      <div className="two-up">
        <section className="ledger">
          <div className="ledger-head">
            <Label info="Charts you have never played whose constant sits where a first pass should already be worth a place in your best 50. The numbers are the range of constants searched. Banks means the score would count but not raise your rating yet.">
              new charts to try · {picks.newWindow[0].toFixed(1)}–{picks.newWindow[1].toFixed(1)}
            </Label>
          </div>
          {picks.newCharts.length === 0 ? (
            <Empty>Nothing unplayed fits this window.</Empty>
          ) : (
            <table className="tbl compact">
              <tbody>
                {picks.newCharts.map((n) => (
                  <tr key={`${n.title}|${n.chart_type}|${n.difficulty}`}>
                    <td className="c-jacket">
                      <Jacket cover={n.cover} size={32} />
                    </td>
                    <td className="c-title">
                      <TitleLink title={n.title} type={n.chart_type} difficulty={n.difficulty} onOpen={onOpen} />
                      <Chip difficulty={n.difficulty} level={n.level} constant={n.constant} type={n.chart_type} />
                    </td>
                    <td className="c-num mono" data-l="first pass">
                      ~{n.expected_accuracy.toFixed(1)}% <b>{n.expected_rank}</b>
                    </td>
                    <td className="c-num mono dim" data-l="odds of S">{Math.round(n.odds_of_s * 100)}%</td>
                    <td className="c-num mono gain" data-l="gain">{n.rating_gain > 0 ? `+${n.rating_gain}` : <span className="dim">banks</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="ledger">
          <div className="ledger-head">
            <Label info="Charts that would enter your best 50 if you scored on them what you usually score at their level. Where the score you hold is far below that, it is read as one run that went badly rather than a chart you cannot play: Usually is what the model expects from you, and Needs is what it takes to get in.">within reach of your best 50</Label>
          </div>
          {near.length === 0 ? (
            <Empty>Nothing is within reach of your best 50 right now.</Empty>
          ) : (
            <table className="tbl compact nojacket">
              <tbody>
                {near.slice(0, 10).map((r) => (
                  <tr key={`${r.song}|${r.chart_type}|${r.difficulty_type}`}>
                    <td className="c-title">
                      <TitleLink title={r.song} type={r.chart_type} difficulty={r.difficulty_type} onOpen={onOpen} />
                      <Chip difficulty={r.difficulty_type} level={r.level} constant={r.difficulty} type={r.chart_type} />
                    </td>
                    <td className="c-num mono" data-l="now">{pct(r.current_accuracy)}</td>
                    <td className="c-num mono dim" data-l="usually">{r.expected ? `${r.expected.toFixed(2)}%` : "—"}</td>
                    <td className="c-num mono" data-l="needs">
                      <b>{pct(r.required_accuracy)}</b>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  );
}
