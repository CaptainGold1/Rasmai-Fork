import { useMemo, useRef, useState } from "react";
import { getJSON, type ChartRow } from "./api";
import { Chip, Empty, Jacket, Label, Lamp, num, pct } from "./bits";
import { TitleLink, type OpenChart } from "./bits";

const DIFFS = ["all", "remaster", "master", "expert", "advanced", "basic"];
const RANKS = ["all", "SSS+", "SSS", "SS+", "SS", "S+", "S", "AAA", "AA", "A", "below A"];
type SortKey = "rating" | "constant" | "accuracy" | "title" | "plays" | "dx" | "bestMatch";
const SORTS: { key: SortKey; desc: boolean; label: string }[] = [
  { key: "rating", desc: true, label: "rating, high first" },
  { key: "bestMatch", desc: true, label: "best search match"},
  { key: "constant", desc: true, label: "constant, high first" },
  { key: "constant", desc: false, label: "constant, low first" },
  { key: "accuracy", desc: false, label: "weakest first" },
  { key: "accuracy", desc: true, label: "strongest first" },
  { key: "dx", desc: true, label: "DX score, high first" },
  { key: "plays", desc: true, label: "most played" },
  { key: "title", desc: false, label: "title, A to Z" },
];

export function Charts({ rows, onOpen }: { rows: ChartRow[]; onOpen?: OpenChart }) {
  const [query, setQuery] = useState("");
  const [diff, setDiff] = useState("all");
  const [type, setType] = useState("all");
  const [rank, setRank] = useState("all");
  const [pool, setPool] = useState("all");
  const [sort, setSort] = useState<SortKey>("rating");
  const [desc, setDesc] = useState(true);
  const [shown, setShown] = useState(100);
  const [titles, setTitles] = useState<string[] | null>(null);
  const timerId = useRef<number | null>(null);

  function getTitlesJson(query: string): Promise<{ titles: string[] }> {
    return getJSON<{ titles: string[] }>(`/api/me/titles?q=${encodeURIComponent(query)}`);
  }

  function executeTitleSearch(query: string): void {
    // console.log(`Searching for titles with query ${query}`);
    query = query.trim();
    if (query.length < 1) {
      setTitles(null);
      return;
    }
    getTitlesJson(query)
      .then((result) => {
        if (result.titles.length < 1) {
          setTitles([]);
          // console.log("Empty titles result");
        } else {
          setTitles(result.titles);
          // console.log(result.titles);
        }
      })
      .catch((err) => {
        console.error(err); // TODO: this should probably display an actual error
      })
  }

  function searchTitles(query: string) {
    query = query.trim();
    // console.log(`searching with query ${query}`);
    if (timerId.current) {
      window.clearTimeout(timerId.current);
      // console.log(`cancelling previous search`);
    }
    if (query.length < 1) {
      setTitles(null);
      return;
    }

    timerId.current = window.setTimeout(() => {
      timerId.current = null;
      executeTitleSearch(query)
    }, 220);
  }

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    // "13.8" is a constant, "13" or "13+" a level; anything else is looked for in the title and artist
    const constant = /^\d{1,2}\.\d$/.test(q) ? Number(q) : null;
    const level = /^\d{1,2}\+?$/.test(q) ? q : null;
    const out = rows.filter((r) => {
      if (diff !== "all" && r.difficulty !== diff) return false;
      if (type !== "all" && r.type !== type) return false;
      if (pool === "new" && !r.new) return false;
      if (pool === "old" && r.new) return false;
      if (pool === "b50" && !r.inBest50) return false;
      if (rank !== "all") {
        if (rank === "below A") {
          if (["SSS+", "SSS", "SS+", "SS", "S+", "S", "AAA", "AA", "A"].includes(r.rank)) return false;
        } else if (r.rank !== rank) return false;
      }
      if (constant !== null) return Math.abs(r.constant - constant) < 0.05;
      if (level !== null) return r.level === level;
      // TODO: there's some small issue where it treats "13." as searching, could fix if you wanted to
      if (titles && !titles.includes(r.title)) {
        // Perform the old substring check as well, if it fails both, it's excluded, if it passes either it gets included
        if (q && !r.title.toLowerCase().includes(q) && !r.artist.toLowerCase().includes(q)) return false;
      }
      return true;
    });
    const dir = desc ? -1 : 1;
    out.sort((a, b) => {
      if (sort === "title") return dir * a.title.localeCompare(b.title, "ja");
      if (sort === "bestMatch") {
        if (titles) {
          const aLocation = titles.findIndex((item) => item === a.title);
          const bLocation = titles.findIndex((item) => item === b.title);

          if (aLocation === bLocation) return b.rating - a.rating
          else if (aLocation === -1) return 1 // If a doesn't exist in the titles array and b does, b comes first
          else if (bLocation === -1) return -1 // If b doesn't exist in the titles array and a does, a comes first
          else return aLocation - bLocation;
        } else return b.rating - a.rating;
      }
      const av = a[sort] as number;
      const bv = b[sort] as number;
      if (av === bv) return b.rating - a.rating;
      return dir * (av - bv);
    });
    return out;
  }, [rows, query, diff, type, rank, pool, sort, desc, titles]);

  const header = (key: SortKey, label: string, cls = "", span = 1) => (
    <th className={`${cls} sortable ${sort === key ? "on" : ""}`} colSpan={span} aria-sort={sort === key ? (desc ? "descending" : "ascending") : "none"}>
      <button
        type="button"
        className="sort-btn"
        onClick={() => {
          if (sort === key) setDesc(!desc);
          else {
            setSort(key);
            setDesc(key !== "title");
          }
        }}
      >
        {label}
        {sort === key ? <span className="arrow" aria-hidden="true">{desc ? "▾" : "▴"}</span> : null}
      </button>
    </th>
  );

  const totalRating = filtered.reduce((s, r) => s + r.rating, 0);
  return (
    <>
      <div className="filters">
        <input
          className="search"
          type="text"
          role="searchbox"
          placeholder="title, artist, level 13+ or constant 13.8"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            searchTitles(e.target.value);
          }}
          onKeyDown={(e) => {
            // If you wanted to, you could make this automatically redirect to a lookup for the top song result.
            // I don't think this is actually a good idea though, since with the (good) default sorting (rating, high first),
            // the top result can be a bad title match (if you have a better score on something that is a worse title match).
            // And just redirecting to the best title match doesn't work either, since the user would expect to be redirected
            // to the top search result.
            const wanted = query.trim();
            if (e.key !== "Enter" || wanted.length < 1) return;
            if (timerId.current) {
              // typed and entered inside the debounce: the hits on hand belong to an earlier query
              window.clearTimeout(timerId.current);
              timerId.current = null;
              return;
            }
            executeTitleSearch(wanted);
          }}
        />
        <select value={diff} onChange={(e) => setDiff(e.target.value)} aria-label="Difficulty">
          {DIFFS.map((d) => (
            <option key={d} value={d}>
              {d === "all" ? "every difficulty" : d === "remaster" ? "Re:MASTER" : d.toUpperCase()}
            </option>
          ))}
        </select>
        <select value={type} onChange={(e) => setType(e.target.value)} aria-label="Chart type">
          <option value="all">DX and standard</option>
          <option value="dx">DX only</option>
          <option value="std">standard only</option>
        </select>
        <select value={rank} onChange={(e) => setRank(e.target.value)} aria-label="Rank">
          {RANKS.map((r) => (
            <option key={r} value={r}>
              {r === "all" ? "any rank" : r}
            </option>
          ))}
        </select>
        <select value={pool} onChange={(e) => setPool(e.target.value)} aria-label="Pool">
          <option value="all">all charts</option>
          <option value="b50">in my best 50</option>
          <option value="new">current version</option>
          <option value="old">older versions</option>
        </select>
        <select
          value={`${sort}|${desc ? "d" : "a"}`}
          onChange={(e) => {
            const [key, dir] = e.target.value.split("|");
            setSort(key as SortKey);
            setDesc(dir === "d");
          }}
          aria-label="Sort"
        >
          {SORTS.map((s) => (
            <option key={`${s.key}|${s.desc ? "d" : "a"}`} value={`${s.key}|${s.desc ? "d" : "a"}`}>
              {s.label}
            </option>
          ))}
        </select>
      </div>
      <div className="ledger-head">
        <Label info="Every chart you have a score on, with the filters above applied. Rating is what each chart is worth toward your best 50 and Lamp is the full combo and full sync marks.">
          {num(filtered.length)} of {num(rows.length)} charts
        </Label>
        <span className="mono hint">{num(totalRating)} rating across the selection</span>
      </div>
      {filtered.length === 0 ? (
        <Empty>Nothing matches those filters.</Empty>
      ) : (
        <div className="scroll">
        <table className="tbl">
          <thead>
            <tr>
              {header("title", "Chart", "c-title-h", 2)}
              {header("constant", "Const", "c-num")}
              {header("accuracy", "Achievement", "c-num")}
              <th>Rank</th>
              <th>Lamp</th>
              {header("dx", "DX score", "c-num")}
              {header("plays", "Plays", "c-num")}
              {header("rating", "Rating", "c-num")}
            </tr>
          </thead>
          <tbody>
            {filtered.slice(0, shown).map((r) => (
              <tr key={`${r.title}|${r.type}|${r.difficulty}`} className={r.inBest50 ? "in-b50" : ""}>
                <td className="c-jacket">
                  <Jacket cover={r.cover} size={32} />
                </td>
                <td className="c-title">
                  <TitleLink title={r.title} type={r.type} difficulty={r.difficulty} onOpen={onOpen} />
                  <Chip difficulty={r.difficulty} level={r.level} constant={r.constant} type={r.type} />
                  {r.inBest50 && <span className="tag-b50">best 50</span>}
                  {r.estimated && (
                    <span className="tag-est" title="Not in the chart database yet: the constant is the middle of its level, and the rating from it is a guess. The database refreshes itself when a read meets a song it does not know.">
                      new song · constant estimated
                    </span>
                  )}
                </td>
                <td className="c-num mono" data-l="const">{r.constant.toFixed(1)}</td>
                <td className="c-num mono strong" data-l="achievement">{pct(r.accuracy, 4)}</td>
                <td className="mono" data-l="rank">{r.rank}</td>
                <td data-l="lamp">
                  <Lamp fc={r.fc} fs={r.fs} />
                </td>
                <td className="c-num mono dim" data-l="dx score">
                  {r.dx > 0 ? num(r.dx) : "—"}
                  {r.maxDx > 0 && r.dx > 0 ? <small> / {num(r.maxDx)}</small> : null}
                </td>
                <td className="c-num mono dim" data-l="plays">{r.plays > 0 ? r.plays : "—"}</td>
                <td className="c-num mono strong" data-l="rating">{r.rating}</td>
              </tr>
            ))}
          </tbody>
        </table>
        </div>
      )}
      {filtered.length > shown && (
        <div className="more">
          <button type="button" className="button ghost" onClick={() => setShown(shown + 200)}>
            {/* TODO: I think I need to fix this to actually query the remaining titles from the backend when pressed, as of now I believe it won't show past 100 titles */}
            show {Math.min(200, filtered.length - shown)} more
          </button>
        </div>
      )}
    </>
  );
}
