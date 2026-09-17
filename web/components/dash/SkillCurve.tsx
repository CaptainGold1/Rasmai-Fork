"use client";

import { useMemo } from "react";
import type { ChartRow } from "./api";
import { Label } from "./bits";

export type CurvePoint = { c: number; e: number; s: number };

type Props = {
  curve: CurvePoint[];
  charts: ChartRow[] | null;
  comfort?: number;
  reach?: number;
  playedCeiling?: number;
};

const W = 720;
const H = 300;
const PAD = { left: 44, right: 14, top: 14, bottom: 30 };

/** The fitted curve with the spread around it, and every score the player holds behind it. */
// Constants land on a tenth, so every chart of the same difficulty shares one x and the dots stack
// into a vertical stripe: 37 charts at 12.8 read as a line rather than as 37 scores. Each dot is
// nudged sideways within its own tenth, by a number derived from the chart itself so it lands in the
// same place on every render, which shows how many are really there without moving any of them into
// a constant they do not have.
const SPREAD = 0.035;

function nudge(key: string): number {
  let hash = 0;
  for (let i = 0; i < key.length; i += 1) hash = (hash * 31 + key.charCodeAt(i)) % 100000;
  return ((hash / 100000) * 2 - 1) * SPREAD;
}

export function SkillCurve({ curve, charts, comfort, reach, playedCeiling }: Props) {
  const scored = useMemo(
    () => (charts ?? []).filter((c) => c.constant > 0 && c.accuracy > 0 && c.difficulty !== "utage"),
    [charts],
  );

  const shape = useMemo(() => {
    if (curve.length < 2) return null;
    // only where the player actually plays: the curve runs to 15 but nobody has scores down at 2
    const lowest = scored.length ? Math.min(...scored.map((c) => c.constant)) : curve[0].c;
    const highest = scored.length ? Math.max(...scored.map((c) => c.constant)) : curve[curve.length - 1].c;
    const raw = curve.filter((p) => p.c >= Math.floor(lowest * 2) / 2 - 0.2 && p.c <= highest + 0.05);
    if (raw.length < 2) return null;
    // the fit steps between half-constant buckets, so up where charts are thin one abandoned run
    // makes the line jump. A short rolling mean draws the shape without inventing or hiding any of it.
    const SMOOTH = 3;
    const points = raw.map((p, i) => {
      const from = Math.max(0, i - SMOOTH);
      const to = Math.min(raw.length - 1, i + SMOOTH);
      const window = raw.slice(from, to + 1);
      return {
        c: p.c,
        e: window.reduce((sum, q) => sum + q.e, 0) / window.length,
        s: window.reduce((sum, q) => sum + q.s, 0) / window.length,
      };
    });
    const x0 = points[0].c;
    const x1 = points[points.length - 1].c;
    const lowAcc = Math.min(93, ...points.map((p) => p.e - p.s), ...scored.map((c) => c.accuracy));
    const y0 = Math.max(80, Math.floor(lowAcc * 2) / 2);
    const y1 = 101;
    const x = (c: number) => PAD.left + ((c - x0) / Math.max(0.1, x1 - x0)) * (W - PAD.left - PAD.right);
    const y = (a: number) => PAD.top + (1 - (Math.min(y1, Math.max(y0, a)) - y0) / (y1 - y0)) * (H - PAD.top - PAD.bottom);
    const line = points.map((p) => `${x(p.c).toFixed(1)},${y(p.e).toFixed(1)}`).join(" ");
    const band = [
      ...points.map((p) => `${x(p.c).toFixed(1)},${y(p.e + p.s).toFixed(1)}`),
      ...[...points].reverse().map((p) => `${x(p.c).toFixed(1)},${y(p.e - p.s).toFixed(1)}`),
    ].join(" ");
    const ticks: number[] = [];
    for (let c = Math.ceil(x0); c <= x1; c += 1) ticks.push(c);
    const rows: number[] = [];
    for (let a = Math.ceil(y0); a <= y1; a += 2) rows.push(a);
    return { points, x, y, x0, x1, y0, y1, line, band, ticks, rows };
  }, [curve, scored]);

  if (!shape) return null;
  const { x, y, x0, x1, y0, line, band, ticks, rows } = shape;
  const marks = (
    [
      [comfort, "comfortable", "comfort"],
      [reach, "S expected", "reach"],
      [playedCeiling, "hardest played", "ceiling"],
    ] as [number | undefined, string, string][]
  ).filter(([value]) => value && value >= x0 && value <= x1);

  return (
    <section className="ledger">
      <div className="ledger-head">
        <Label info="The line is what the model expects you to score at each chart constant, fitted to your own results. The band around it is how much your scores usually vary. Each dot is one chart you hold a score on, so a dot below the band is a chart you under-perform on and one above it is a chart you beat your own curve on.">
          your curve
        </Label>
        <span className="mono hint">{scored.length} scored charts behind it</span>
      </div>
      <svg className="curve" viewBox={`0 0 ${W} ${H}`} role="img" aria-label="what you score against chart constant">
        {rows.map((a) => (
          <g key={a}>
            <line x1={PAD.left} y1={y(a)} x2={W - PAD.right} y2={y(a)} className="curve-grid" />
            <text x={PAD.left - 7} y={y(a) + 3} textAnchor="end" className="curve-axis">
              {a}
            </text>
          </g>
        ))}
        {ticks.map((c) => (
          <text key={c} x={x(c)} y={H - PAD.bottom + 15} textAnchor="middle" className="curve-axis">
            {c}
          </text>
        ))}
        <polygon points={band} className="curve-band" />
        {scored.map((chart) => (
          <circle
            key={`${chart.title}|${chart.type}|${chart.difficulty}`}
            cx={x(chart.constant + nudge(`${chart.title}|${chart.type}|${chart.difficulty}`))}
            cy={y(chart.accuracy)}
            r={2}
            className={`curve-dot d-${chart.difficulty}`}
          >
            <title>{`${chart.title} · ${chart.difficulty} ${chart.level} · ${chart.constant.toFixed(1)} · ${chart.accuracy.toFixed(4)}%`}</title>
          </circle>
        ))}
        <polyline points={line} className="curve-line" />
        {marks.map(([value, label, cls], i) => {
          const at = x(value as number);
          // the labels stack on their own rows and hug whichever side they are nearest, so two
          // markers a few tenths apart never print over each other
          const row = PAD.top + 11 + i * 13;
          const near = at > W - PAD.right - 70;
          return (
            <g key={label}>
              <line x1={at} y1={PAD.top} x2={at} y2={H - PAD.bottom} className={`curve-mark ${cls}`} />
              <text
                x={near ? at - 5 : at + 5}
                y={row}
                className={`curve-mark-label ${cls}`}
                textAnchor={near ? "end" : "start"}
              >
                {label} {(value as number).toFixed(1)}
              </text>
            </g>
          );
        })}
        <text x={W - PAD.right} y={H - 4} textAnchor="end" className="curve-axis dim">
          chart constant →
        </text>
        <text x={4} y={PAD.top + 4} className="curve-axis dim">
          achievement
        </text>
      </svg>
      <div className="curve-keys">
        {([["basic", "#4bb85f"], ["advanced", "#e0a020"], ["expert", "#e2455a"], ["master", "#a266e8"], ["remaster", "#cbbbe8"]] as [string, string][])
          .filter(([tier]) => scored.some((c) => c.difficulty === tier))
          .map(([tier, colour]) => (
            <span key={tier}>
              <i style={{ background: colour }} />
              {tier === "remaster" ? "Re:MASTER" : tier}
            </span>
          ))}
      </div>
      <p className="hint">
        Dots below the band are where the picks come from. The band widens where you have played less: the model is less sure there.
      </p>
    </section>
  );
}
