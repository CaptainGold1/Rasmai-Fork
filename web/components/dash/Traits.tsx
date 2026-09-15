import { useMemo } from "react";
import type { JudgementProfileData, Trait, TraitPractice } from "./api";
import { Empty, Info, Jacket, Label, TitleLink, type OpenChart } from "./bits";

// what a chart is rather than what it asks of the hands. The bot measures these, because a
// charter's habits soak up differences that would otherwise be blamed on a pattern, but a trait
// is only worth naming if it is a skill you can work on. Kept in step with NOT_A_SKILL in tags.py.
const NOT_A_SKILL = new Set(["type", "era", "genre", "designer"]);
const LEAN = 0.3;
const CONFIRM_CHARTS = 12;
const TIER = { basic: "BAS", advanced: "ADV", expert: "EXP", master: "MAS", remaster: "Re:M" } as Record<string, string>;

const RADAR_MIN = 3;
const RADAR_FILL = 6;

type Axis = Trait & { filler?: boolean };
const isLean = (a: Trait) => Boolean(a.leaning) && !a.verified;
const isEven = (a: Trait) => !a.verified && !a.leaning && a.count >= CONFIRM_CHARTS && Math.abs(a.offset) < LEAN;

/** Pick the axes the wheel is drawn on: confirmed and leaning traits about play, both halves so the shape has contrast.
 *  A wheel with fewer than six is rounded out with the groups the player plays evenly, which sit on the middle ring. */
export function radarAxes(axes: Trait[], limit = 8): Axis[] {
  const pool: Axis[] = axes.filter((a) => (a.verified || a.leaning) && !NOT_A_SKILL.has(a.dimension));
  if (pool.length < RADAR_FILL) {
    const fillers = axes.filter((a) => isEven(a) && !NOT_A_SKILL.has(a.dimension)).sort((a, b) => Math.abs(b.offset) - Math.abs(a.offset));
    pool.push(...fillers.slice(0, Math.max(0, RADAR_FILL - pool.length)).map((a) => ({ ...a, filler: true })));
    if (pool.length < RADAR_MIN) return [];
  }
  const half = Math.floor(limit / 2);
  const up = pool.filter((a) => a.offset > 0).sort((a, b) => b.offset - a.offset).slice(0, half);
  const down = pool.filter((a) => a.offset < 0).sort((a, b) => a.offset - b.offset).slice(0, limit - half);
  const chosen = [...up, ...down];
  if (chosen.length < limit) {
    const rest = [...pool].sort((a, b) => Math.abs(b.offset) - Math.abs(a.offset)).filter((a) => !chosen.includes(a));
    chosen.push(...rest.slice(0, limit - chosen.length));
  }
  return chosen.sort((a, b) => b.offset - a.offset);
}

/** How many character cells a label takes, counting East Asian characters as two. */
function textWidth(text: string): number {
  let cells = 0;
  for (const char of text) cells += char.codePointAt(0)! > 0x2e7f ? 2 : 1;
  return cells;
}

/** Split a label into at most two lines of roughly equal length, cutting a line that still overflows. */
function wrapLabel(text: string, width = 14): string[] {
  const cut = (line: string) => {
    if (textWidth(line) <= width + 4) return line;
    let kept = "";
    for (const char of line) {
      if (textWidth(kept + char) > width + 3) break;
      kept += char;
    }
    return kept.trimEnd() + "…";
  };
  if (textWidth(text) <= width) return [text];
  // a bracketed qualifier reads best whole on its own line
  const bracket = text.lastIndexOf(" (");
  if (bracket > 0 && text.endsWith(")")) {
    const name = text.slice(0, bracket);
    const qualifier = text.slice(bracket + 1);
    if (textWidth(name) <= width + 4 && textWidth(qualifier) <= width + 4) return [name, qualifier];
  }
  // an ampersand joins two names with no space around it, so it is a place to break as well
  const words = text.match(/\S+?[＆&]|\S+/g) ?? [text];
  // a lone ampersand stays with the word before it, so no line starts with one
  for (let i = words.length - 1; i > 0; i--) {
    if (words[i] === "&" || words[i] === "＆") words.splice(i - 1, 2, `${words[i - 1]} ${words[i]}`);
  }
  if (words.length < 2) return [cut(text)];
  let best: [string, string] | null = null;
  let bestScore = Infinity;
  for (let i = 1; i < words.length; i++) {
    const pair: [string, string] = [words.slice(0, i).join(" "), words.slice(i).join(" ")];
    const score = Math.max(textWidth(pair[0]), textWidth(pair[1]));
    if (score < bestScore) {
      best = pair;
      bestScore = score;
    }
  }
  return best!.map(cut);
}

/** The wheel itself. The middle ring is the player's own average; outward is stronger. A hollow point is a leaning trait. */
export function Radar({ axes }: { axes: Axis[] }) {
  const width = 520;
  const height = 420;
  const midX = width / 2;
  const midY = height / 2;
  const radius = midY - 72;
  const at = (i: number, reach: number) => {
    const angle = (2 * Math.PI * i) / axes.length;
    return [midX + radius * reach * Math.sin(angle), midY - radius * reach * Math.cos(angle)] as const;
  };
  const ring = (r: number) => axes.map((_, i) => at(i, r).join(",")).join(" ");
  const reachOf = (a: Axis) => Math.max(0.12, Math.min(1, 0.5 + a.offset / 2));
  const shape = axes.map((a, i) => at(i, reachOf(a)).join(",")).join(" ");
  const labelReach = (radius + 18) / radius;
  return (
    <svg className="radar" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="your traits against your own average">
      {[0.25, 0.5, 0.75, 1].map((r) => (
        <polygon key={r} points={ring(r)} className={r === 0.5 ? "ring mid" : "ring"} />
      ))}
      {axes.map((a, i) => {
        const [x, y] = at(i, 1);
        return <line key={a.label} x1={midX} y1={midY} x2={x} y2={y} className="spoke" />;
      })}
      <polygon points={shape} className="shape" />
      {axes.map((a, i) => {
        const [x, y] = at(i, reachOf(a));
        const [lx, ly] = at(i, labelReach);
        const sin = Math.sin((2 * Math.PI * i) / axes.length);
        const anchor = Math.abs(sin) < 0.35 ? "middle" : sin > 0 ? "start" : "end";
        const lines = wrapLabel(a.english ?? a.label);
        // the name and its value stack away from the wheel: above it at the top, below it at the
        // bottom, centred at the sides, so a two-line name never runs into its own point
        const block = (lines.length - 1) * 13 + 14;
        const firstY = ly - block / 2 - Math.cos((2 * Math.PI * i) / axes.length) * (block / 2);
        const valueY = firstY + block;
        return (
          <g key={a.label}>
            <circle cx={x} cy={y} r={isLean(a) || a.filler ? 4.5 : 4} className={isLean(a) || a.filler ? "dot lean" : "dot"} />
            {lines.map((line, row) => (
              <text key={row} x={lx} y={firstY + row * 13} textAnchor={anchor} className={`axis ${a.filler ? "even" : a.offset < 0 ? "down" : "up"}`}>
                {line}
              </text>
            ))}
            <text x={lx} y={valueY} textAnchor={anchor} className="axis-val">
              {a.offset > 0 ? "+" : ""}
              {a.offset.toFixed(2)}
              {isLean(a) || a.filler ? " ?" : ""}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

function chance(p?: number): string {
  if (!p) return "";
  const n = Math.max(1, Math.round(1 / Math.max(p, 0.001)));
  return `1 in ${n} shuffles matched it`;
}

function List({ items, tone, empty }: { items: Trait[]; tone: "down" | "up"; empty: string }) {
  if (!items.length) return <p className="hint">{empty}</p>;
  return (
    <ul className="traits">
      {items.map((t) => (
        <li key={`${t.dimension}:${t.label}`}>
          <span className={`mono trait-offset ${tone}`}>
            {t.offset > 0 ? "+" : ""}
            {t.offset.toFixed(2)}
          </span>
          <span className="trait-label">
            {t.english ?? t.label}
            {isLean(t) ? <span className="trait-lean">leaning</span> : null}
          </span>
          <span className="mono dim" title={`${t.count} charts${t.plays ? `, ${t.plays} plays` : ""}${t.p ? ` · ${chance(t.p)}` : ""}`}>
            {t.count}
            {t.plays ? <small> · {t.plays} plays</small> : null}
          </span>
        </li>
      ))}
    </ul>
  );
}

function Practice({ items, onOpen }: { items: TraitPractice[]; onOpen?: OpenChart }) {
  return (
    <ul className="practice">
      {items.map((p) => (
        <li key={p.label}>
          <div className="practice-head">
            <span className="mono trait-offset down">{p.offset.toFixed(2)}</span>
            <span>
              {p.english}
              {p.verified ? null : <span className="trait-lean">leaning</span>}
            </span>
            <span className="mono">{p.count} charts</span>
          </div>
          <ul>
            {p.charts.map((c) => (
              <li key={`${c.title}:${c.chart_type}:${c.difficulty}`}>
                <Jacket cover={c.cover} size={28} />
                <span>
                  <TitleLink title={c.title} type={c.chart_type} difficulty={c.difficulty} onOpen={onOpen} />{" "}
                  <span className="mono dim">
                    {TIER[c.difficulty] ?? c.difficulty} {c.level} · {c.constant.toFixed(1)} {c.chart_type.toUpperCase()}
                  </span>
                </span>
                <span className="mono">{c.accuracy !== null ? `you hold ${c.accuracy.toFixed(4)}%` : "not played yet"}</span>
              </li>
            ))}
          </ul>
        </li>
      ))}
    </ul>
  );
}

export function Traits({ traits, axes, charts, practice, onOpen }: { traits: Trait[]; axes: Trait[]; charts: number; practice?: TraitPractice[]; onOpen?: OpenChart }) {
  // the confirmed list arrives already filtered; the leaning and level ones are built here, so
  // the same rule has to be applied before anything is counted or drawn
  const all = useMemo(() => (axes ?? []).filter((a) => !NOT_A_SKILL.has(a.dimension)), [axes]);
  const wheel = useMemo(() => radarAxes(all), [all]);
  const confirmed = traits.filter((t) => t.verified !== false);
  const leaning = all.filter(isLean);
  const even = all.filter(isEven).sort((a, b) => b.count - a.count);
  const shown = [...confirmed, ...leaning];
  const weak = shown.filter((t) => t.offset < 0).sort((a, b) => a.offset - b.offset).slice(0, 8);
  const strong = shown.filter((t) => t.offset > 0).sort((a, b) => b.offset - a.offset).slice(0, 8);
  const largest = [...all].sort((a, b) => Math.abs(b.offset) - Math.abs(a.offset)).slice(0, 4);
  const gate =
    "Confirmed: rarer than 1 in 50 under shuffled tags and the same sign in both halves of your charts, three splits over. Leaning: points one way but has not passed that, so read it as a hint. Only confirmed traits steer your picks and /new focus.";

  if (!shown.length) {
    return (
      <section className="ledger">
        <div className="ledger-head">
          <Label info={`Your traits: what your charts share, a pattern, a note mix, a tempo band, an era, a designer, scored by how far your results sit from your own curve. Once enough plays are stored, each note type joins them, measured from your judgement pages rather than inferred from scores. ${gate}`}>how you play</Label>
          <span className="mono hint">
            {all.length} groups measured · {charts} scored charts
          </span>
        </div>
        <Empty>
          Nothing separates from noise yet. Every trait group measured sits too close to your usual score to trust, or has too few charts behind it. Every recorded
          play counts, not only your bests, so more plays sharpen this.
        </Empty>
        {largest.length ? (
          <>
            <div className="ledger-head">
              <Label info="The four groups furthest from your usual score. None passed the gate, so treat them as things to watch, not facts.">largest measured, none confirmed</Label>
            </div>
            <ul className="traits">
              {largest.map((t) => (
                <li key={`${t.dimension}:${t.label}`}>
                  <span className={`mono trait-offset ${t.offset < 0 ? "down" : "up"}`}>
                    {t.offset > 0 ? "+" : ""}
                    {t.offset.toFixed(2)}
                  </span>
                  <span className="trait-label">{t.english ?? t.label}</span>
                  <span className="mono dim">{t.count}</span>
                  <span className="trait-when">{chance(t.p)}</span>
                </li>
              ))}
            </ul>
          </>
        ) : null}
        {even.length ? <EvenLine even={even} /> : null}
      </section>
    );
  }
  return (
    <>
      <section className="ledger">
        <div className="ledger-head">
          <Label info={`Your traits: what your charts share, a pattern, a note mix, a tempo band, an era, a designer, scored by how far your results sit from your own curve. Once enough plays are stored, each note type joins them, measured from your judgement pages rather than inferred from scores. Every tag is fitted together over your bests and every recorded play, with play count and difficulty held fixed. ${gate} Patterns and note mixes come from maiノーツ.`}>how you play</Label>
          <span className="mono hint">
            {confirmed.length} confirmed · {leaning.length} leaning · {even.length} level with the rest · {charts} scored charts
          </span>
        </div>
        <div className="two-up radar-split">
          <div className="radar-wrap">
            <Info text="Each axis is one of your play traits: patterns, note mix, tempo, density. The middle ring is your own average: a point further out means you score above it on those charts, further in means below. A hollow point with a ? is not confirmed: leaning one way, or a group you play level with the rest, shown in grey." />
            {wheel.length >= RADAR_MIN ? <Radar axes={wheel} /> : <p className="hint">The wheel appears once three or more play traits have enough charts behind them.</p>}
          </div>
          <div>
            <div className="ledger-head">
              <Label info="Traits where your scores sit below your own curve. The number is the gap in achievement points. The small figure counts the charts sharing the trait, or the plays behind it for a note type. Hover it for how rarely shuffled tags matched it.">where you lose points</Label>
            </div>
            <List items={weak} tone="down" empty="Nothing sits below your own average, confirmed or leaning." />
            <div className="ledger-head">
              <Label info="Traits where your scores sit above your own curve.">where you shine</Label>
            </div>
            <List items={strong} tone="up" empty="Nothing sits above your own average yet, confirmed or leaning." />
          </div>
        </div>
        {practice?.length ? (
          <>
            <div className="ledger-head">
              <Label info="For each pattern you score below your curve on, a few charts inside your own working band that carry it. Ones you already hold a score on come first, so a rerun shows the change. The Look up tab's pattern browser lists every chart with the tag.">what to work on</Label>
            </div>
            <Practice items={practice} onOpen={onOpen} />
          </>
        ) : null}
        {even.length ? <EvenLine even={even} /> : null}
      </section>
    </>
  );
}

/** What the judgement pages of the recent plays say, measured rather than inferred: where the points go, and early or late. */
export function JudgementProfile({ data }: { data: JudgementProfileData | null }) {
  const weak = data?.types.find((t) => t.kind === data.weak);
  const share = data?.lateShare ?? null;
  const timing =
    share === null
      ? ""
      : share >= 0.6
        ? `Your off-timing hits land late ${Math.round(share * 100)}% of the time: a touch behind the beat.`
        : share <= 0.4
          ? `Your off-timing hits land early ${Math.round((1 - share) * 100)}% of the time: a touch ahead of the beat.`
          : "Your off-timing hits split evenly between fast and late.";
  return (
    <section className="ledger">
      <div className="ledger-head">
        <Label info="Measured from the judgement pages of your recent plays, not inferred from scores: how many notes of each type you hit, what each type cost, and whether your hits land early or late. Every read collects the pages for new plays, so this grows as you play.">
          judgements
        </Label>
        <span className="mono hint">{data ? `${data.plays} plays read · ${data.lostPerPlay.toFixed(2)} points lost per play` : ""}</span>
      </div>
      {!data ? (
        <Empty>
          Needs the judgement pages of three plays. Open a play&apos;s judgements on the Recent tab, or let a read collect them: every command and the daily
          read pick up the pages for new plays.
        </Empty>
      ) : (
        <div className="two-up">
          <table className="tbl compact keep judge-profile">
            <thead>
              <tr>
                <th>notes</th>
                <th className="c-num">of the notes</th>
                <th className="c-num">of the loss</th>
                <th className="c-num">lost per 100</th>
                <th className="c-num">clean</th>
              </tr>
            </thead>
            <tbody>
              {data.types.map((t) => (
                <tr key={t.kind} className={t.kind === data.weak ? "weak" : ""}>
                  <td className="mono kind">{t.kind}</td>
                  <td className="c-num mono">{Math.round(t.share * 100)}%</td>
                  <td className="c-num mono">{Math.round(t.lossShare * 100)}%</td>
                  <td className="c-num mono">{t.per100.toFixed(2)}</td>
                  <td className="c-num mono dim">{Math.round(t.clean * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div>
            <p className="hint">
              {weak
                ? `${weak.kind[0].toUpperCase()}${weak.kind.slice(1)} notes carry ${Math.round(weak.lossShare * 100)}% of what you lose while being ${Math.round(weak.share * 100)}% of the notes: that is the type costing you most.`
                : "No note type costs you out of proportion to its share of the notes."}
            </p>
            <ul className="bars">
              <li>
                <span>fast</span>
                <span className="bar">
                  <span style={{ width: `${data.fast + data.late ? (100 * data.fast) / (data.fast + data.late) : 0}%` }} />
                </span>
                <span className="v">{data.fast}</span>
              </li>
              <li>
                <span>late</span>
                <span className="bar">
                  <span style={{ width: `${data.fast + data.late ? (100 * data.late) / (data.fast + data.late) : 0}%` }} />
                </span>
                <span className="v">{data.late}</span>
              </li>
            </ul>
            {timing ? <p className="hint">{timing}</p> : null}
          </div>
        </div>
      )}
    </section>
  );
}

function EvenLine({ even }: { even: Trait[] }) {
  const names = even.slice(0, 10).map((t) => t.english ?? t.label);
  return (
    <p className="even-line">
      <b>Level with the rest:</b> {names.join(", ")}
      {even.length > 10 ? ` and ${even.length - 10} more` : ""}. Measured over enough charts and within ±{LEAN.toFixed(1)} of your usual score: not a weakness, not a
      strength.
    </p>
  );
}
