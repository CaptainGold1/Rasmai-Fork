"use client";

import { useMemo } from "react";
import { type ChartRow, type Overview } from "./api";
import { Empty, Label, LoadError, num, pct } from "./bits";
import { SkillCurve } from "./SkillCurve";
import { Sparkline } from "./Sparkline";
import { levelValue } from "./Best50";

const RANK_ORDER = ["SSS+", "SSS", "SS+", "SS", "S+", "S", "AAA", "AA", "A", "BBB", "BB", "B", "C", "D"];

export function OverviewTab({ me, charts, chartsError, onRetry }: { me: Overview; charts: ChartRow[] | null; chartsError?: string; onRetry?: () => void }) {
  const stats = useMemo(() => {
    if (!charts) return null;
    const upper = charts.filter((c) => ["expert", "master", "remaster"].includes(c.difficulty));
    const ranks: Record<string, number> = {};
    for (const c of upper) ranks[c.rank] = (ranks[c.rank] ?? 0) + 1;
    const fcPlus = charts.filter((c) => c.fc === "FC+" || c.fc === "AP" || c.fc === "AP+").length;
    const fc = charts.filter((c) => c.fc === "FC").length;
    const ap = charts.filter((c) => c.fc === "AP" || c.fc === "AP+").length;
    const fsPlus = charts.filter((c) => c.fs === "FS+" || c.fs === "FDX" || c.fs === "FDX+").length;
    const levels = new Map<string, { n: number; sum: number }>();
    for (const c of upper) {
      const e = levels.get(c.level) ?? { n: 0, sum: 0 };
      e.n += 1;
      e.sum += c.accuracy;
      levels.set(c.level, e);
    }
    return { upper: upper.length, ranks, fc, fcPlus, ap, fsPlus, levels };
  }, [charts]);
  const prof = me.analysis?.profile;
  const habits = prof?.habits;
  const b50 = me.analysis?.best50;
  return (
    <>
      <Sparkline points={me.history ?? []} />
      {chartsError ? <LoadError what="your charts" message={chartsError} onRetry={onRetry} /> : null}
      {prof?.curve && prof.curve.length > 1 && (
        <SkillCurve
          curve={prof.curve}
          charts={charts}
          comfort={prof.comfortConstant}
          reach={prof.reachConstant}
          playedCeiling={prof.playedCeiling}
        />
      )}
      <div className="two-up">
        <section className="ledger">
          <div className="ledger-head">
            <Label info="Where your scores put you. Comfortable up to is the highest chart constant you still score consistently at, S expected up to is where a first pass should still land an S, and hardest S is the toughest chart you hold an S on. Reachable from your picks is what the What to play targets add up to if every one lands. Charts you pick is how old they were when you played them, so it says whether you chase new releases or work the back catalogue. From re-rating is what your best 50 owes to constants being revised rather than to you playing.">how you play</Label>
          </div>
          <dl className="facts">
            <dt>comfortable up to</dt>
            <dd className="mono">{prof ? prof.comfortConstant.toFixed(1) : "—"}</dd>
            <dt>S expected up to</dt>
            <dd className="mono">{prof ? prof.reachConstant.toFixed(1) : "—"}</dd>
            <dt>hardest S</dt>
            <dd className="mono">{prof ? prof.hardestS.toFixed(1) : "—"}</dd>
            {habits?.age ? (
              <>
                <dt>charts you pick</dt>
                <dd className="mono">
                  {habits.age.medianYears.toFixed(1)} yr old · {Math.round(habits.age.freshShare * 100)}% under a year
                </dd>
              </>
            ) : null}
            {habits?.rerates ? (
              <>
                <dt>from re-rating</dt>
                <dd className="mono">
                  {habits.rerates.rating >= 0 ? "+" : ""}
                  {habits.rerates.rating} over {habits.rerates.charts} charts
                </dd>
              </>
            ) : null}
            {habits?.notes ? (
              <>
                <dt>notes hit</dt>
                <dd className="mono">{num(habits.notes.notes)}</dd>
              </>
            ) : null}
            <dt>charts scored</dt>
            <dd className="mono">{num(me.snapshot?.charts)}</dd>
            <dt>expert and up</dt>
            <dd className="mono">{stats ? num(stats.upper) : "—"}</dd>
            <dt>full combos</dt>
            <dd className="mono">{stats ? `${num(stats.fc + stats.fcPlus)} (${num(stats.ap)} all perfect)` : "—"}</dd>
            <dt>full sync+</dt>
            <dd className="mono">{stats ? num(stats.fsPlus) : "—"}</dd>
            <dt>reachable from your picks</dt>
            <dd className="mono gain">{me.analysis?.reachableGain != null ? `+${me.analysis.reachableGain}` : "—"}</dd>
          </dl>
        </section>
        <section className="ledger">
          <div className="ledger-head">
            <Label info="Your rating is the sum of your best 50 chart ratings: the 15 best on songs from the current version and the 35 best on older ones. Enters at is the chart rating a new score needs to push the lowest one out. Open means that pool is not full yet, so any score counts.">best 50 cutoffs</Label>
          </div>
          <dl className="facts">
            <dt>new pool (15)</dt>
            <dd className="mono">
              {b50 ? `${num(b50.newTotal)} · enters at ${b50.newCutoff}` : "—"}
              {b50 && b50.newSlotsOpen > 0 ? ` · ${b50.newSlotsOpen} open` : ""}
            </dd>
            <dt>old pool (35)</dt>
            <dd className="mono">
              {b50 ? `${num(b50.oldTotal)} · enters at ${b50.oldCutoff}` : "—"}
              {b50 && b50.oldSlotsOpen > 0 ? ` · ${b50.oldSlotsOpen} open` : ""}
            </dd>
          </dl>
          <div className="ledger-head">
            <Label info="How many of your Expert, Master and Re:Master scores sit at each rank.">ranks · expert and up</Label>
          </div>
          {stats ? (
            <ul className="bars">
              {RANK_ORDER.filter((r) => stats.ranks[r]).map((r) => (
                <li key={r}>
                  <span className="mono k">{r}</span>
                  <span className="bar">
                    <span style={{ width: `${(100 * stats.ranks[r]) / stats.upper}%` }} />
                  </span>
                  <span className="mono v">{stats.ranks[r]}</span>
                </li>
              ))}
            </ul>
          ) : (
            <Empty>Loading…</Empty>
          )}
        </section>
      </div>
      {stats && stats.levels.size > 0 && (
        <section className="ledger">
          <div className="ledger-head">
            <Label info="Your average achievement at each level, Expert and up, with how many charts that average covers. The bar starts at 80% and fills at 100%.">average achievement by level · expert and up</Label>
          </div>
          <table className="tbl compact levels keep">
            <tbody>
              {[...stats.levels.entries()]
                .sort((a, b) => levelValue(b[0]) - levelValue(a[0]))
                .map(([level, e]) => (
                  <tr key={level}>
                    <td className="mono strong">{level}</td>
                    <td className="c-num mono dim">{e.n} charts</td>
                    <td className="c-bar">
                      <span className="bar">
                        <span style={{ width: `${Math.max(0, Math.min(100, (e.sum / e.n - 80) * 5))}%` }} />
                      </span>
                    </td>
                    <td className="c-num mono">{pct(e.sum / e.n)}</td>
                  </tr>
                ))}
            </tbody>
          </table>
        </section>
      )}
    </>
  );
}
