import { useEffect, useRef, useState } from "react";
import { ApiError, getJSON, type PatternBrowse } from "./api";
import { Chip, Empty, Jacket, pct } from "./bits";

const LEVELS = ["", "15", "14+", "14", "13+", "13", "12+", "12", "11+", "11", "10+", "10", "9+", "9", "8+", "8", "7+", "7"];

const DIFFS: [string, string][] = [["", "any difficulty"], ["remaster", "Re:MASTER"], ["master", "MASTER"], ["expert", "EXPERT"], ["advanced", "ADVANCED"], ["basic", "BASIC"]];

/** Browse charts by what they ask of you: a trait, narrowed by level or difficulty, with your own scores beside each. */
export function PatternBrowser({ onOpen, open, setOpen, tag, setTag }: {
  onOpen: (title: string, type: string, difficulty: string) => void;
  open: boolean;
  setOpen: (v: boolean) => void;
  tag: string;
  setTag: (v: string) => void;
}) {
  const [find, setFind] = useState("");
  const [level, setLevel] = useState("");
  const [diff, setDiff] = useState("");
  const [data, setData] = useState<PatternBrowse | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const request = useRef(0);      // only the latest request may answer: two quick clicks must not settle on the older list
  useEffect(() => {
    if (!open) return;
    const mine = ++request.current;
    setBusy(true);
    setError("");
    const params = new URLSearchParams({ tag, level, difficulty: diff });
    getJSON<PatternBrowse>(`/api/me/patterns?${params}`)
      .then((d) => {
        if (mine === request.current) setData(d);
      })
      .catch((e: ApiError) => {
        if (mine === request.current) setError(e.message);
      })
      .finally(() => {
        if (mine === request.current) setBusy(false);
      });
  }, [open, tag, level, diff]);
  if (!open) {
    return (
      <button type="button" className="linkish browse-toggle" onClick={() => setOpen(true)}>
        or browse by trait: what a chart asks of you, and every chart that asks it
      </button>
    );
  }
  const tags = data?.tags ?? [];
  const needle = find.trim().toLowerCase();
  const matches = needle
    ? tags.filter((t) => t.tag.toLowerCase().includes(needle) || t.english.toLowerCase().includes(needle) || t.label.toLowerCase().includes(needle))
    : tags;
  const chosen = tags.find((t) => t.tag === data?.tag);     // the trait the list on show belongs to, not the one just clicked
  return (
    <section className="browse">
      <div className="filters">
        <input
          className="search"
          type="search"
          value={find}
          placeholder="Search traits: streams, 乱打, slide-heavy, dense…"
          aria-label="Search traits"
          onChange={(e) => setFind(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && matches.length) setTag(matches[0].tag);
          }}
        />
        <select value={level} onChange={(e) => setLevel(e.target.value)} aria-label="Level">
          {LEVELS.map((l) => (
            <option key={l || "any"} value={l}>
              {l ? `level ${l}` : "any level"}
            </option>
          ))}
        </select>
        <select value={diff} onChange={(e) => setDiff(e.target.value)} aria-label="Difficulty">
          {DIFFS.map(([v, label]) => (
            <option key={v || "any"} value={v}>
              {label}
            </option>
          ))}
        </select>
        <button type="button" className="linkish" onClick={() => setOpen(false)}>
          close
        </button>
      </div>
      {error && <Empty>{error}</Empty>}
      {!error && (
        <ul className="tag-picker">
          {matches.length === 0 && <li className="hint">Nothing matches “{find}”.</li>}
          {matches.map((t) => (
            <li key={t.tag}>
              <button
                type="button"
                className={[t.tag === tag ? "on" : "", t.community ? "" : "measured"].filter(Boolean).join(" ")}
                onClick={() => setTag(t.tag === tag ? "" : t.tag)}
                title={t.community ? `tagged by maiノーツ · ${t.charts} charts` : `measured from each chart · ${t.charts} charts`}
              >
                {t.community ? `${t.english} · ${t.tag}` : t.label}
                <span className="mono"> {t.charts}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {!error && !tag && (
        <p className="hint">
          Solid traits are tagged by maiノーツ's editors, who mark what a chart is made of: streams, jacks, hand swaps, slides that fire off a tap. They have covered
          a third of the Master charts and half the Re:MASTERs, and little below that, so the dashed ones are measured from each chart's own note mix, tempo and density. Pick one to see
          every chart that has it, hardest first, with your score where you have one.
        </p>
      )}
      {tag && data && data.tag && (
        <>
          <p className="hint">
            <b>{chosen && !chosen.community ? chosen.label : data.english}</b>
            {chosen && !chosen.community ? " · measured from each chart" : ` · ${data.tag}`} · {data.charts.length} charts
            {data.charts.some((c) => c.played) ? `, ${data.charts.filter((c) => c.played).length} played` : ""}
            {busy ? " · updating…" : ""}
          </p>
          {data.charts.length === 0 ? (
            <Empty>No playable chart carries this trait at that level or difficulty.</Empty>
          ) : (
            <ul className="hits pattern-list">
              {data.charts.map((c) => (
                <li key={`${c.title}|${c.chart_type}|${c.difficulty}`} className="hit">
                  <Jacket cover={c.cover} size={44} />
                  <button type="button" className="hit-title" onClick={() => onOpen(c.title, c.chart_type, c.difficulty)}>
                    {c.title}
                    <small>
                      {c.played ? `${pct(c.accuracy)} ${c.rank} · ${c.rating}${c.note ? ` · ${c.note}` : ""}` : "never played"}
                      {c.tags.length ? ` · also ${c.tags.join(", ")}` : ""}
                    </small>
                  </button>
                  <div className="hit-charts">
                    <span className={c.played ? "" : "faded"} style={{ display: "contents" }}>
                      <Chip difficulty={c.difficulty} level={c.level} constant={c.constant} type={c.chart_type} />
                    </span>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </section>
  );
}
