import { useEffect, useRef, useState } from "react";
import { ApiError, getJSON, type LookupTarget, type SearchHit, type SongLookup } from "./api";
import { Chip, Empty, Jacket, pct } from "./bits";
import { Detail } from "./Detail";
import { PatternBrowser } from "./PatternBrowser";

/** The Look up tab: find any song, then one chart the way /chart shows it. */
export function Lookup({ target }: { target: LookupTarget | null }) {
  const [query, setQuery] = useState(target?.title ?? "");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [song, setSong] = useState<SongLookup | null>(null);
  const [selected, setSelected] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [browseOpen, setBrowseOpen] = useState(false);
  const [browseTag, setBrowseTag] = useState("");
  const timer = useRef<number | null>(null);
  const opened = useRef<string>("");
  const opening = useRef(0);      // a lookup that a newer search or lookup has overtaken must not land on the page

  // a trait on a chart page opens the browser on that trait, so "what else asks this of me" is one click
  const browseTrait = (key: string) => {
    setSong(null);
    setHits(null);
    setError("");
    setBrowseTag(key);
    setBrowseOpen(true);
  };
  const searchNow = (wanted: string) =>
    getJSON<{ songs: SearchHit[] }>(`/api/me/search?q=${encodeURIComponent(wanted)}`);

  const open = (title: string, type?: string, difficulty?: string, cover?: string) => {
    const mine = ++opening.current;
    setBusy(true);
    setError("");
    const params = new URLSearchParams(cover ? { cover } : { title });
    if (type) params.set("type", type);
    if (difficulty) params.set("difficulty", difficulty);
    getJSON<SongLookup>(`/api/me/chart?${params}`)
      .then((d) => {
        if (mine !== opening.current) return;
        setSong(d);
        setSelected(d.selected);
        setHits(null);
        setQuery(d.title);
        const chart = d.charts[d.selected];
        window.history.replaceState(
          null,
          "",
          `${window.location.pathname}?chart=${encodeURIComponent(d.title)}&type=${chart?.chart_type ?? ""}&difficulty=${chart?.difficulty ?? ""}#chart`,
        );
      })
      .catch((e: ApiError) => {
        if (mine !== opening.current) return;
        setHits(null);
        if (e.status === 404 && e.code === "unknown_song") {
          const rows = (e.body.charts as { level: string; difficulty: string; accuracy: number }[] | undefined) ?? [];
          const yours = rows.map((c) => `${c.difficulty} ${c.level} at ${c.accuracy.toFixed(4)}%`).join(", ");
          setError(
            `"${String(e.body.title ?? title)}" is not in the chart database yet. Reading your scores fetched the database again when it met this song, so the song is newer than the database's own entries; the jacket, constants and this page arrive once it is listed there. Until then your score${rows.length === 1 ? "" : "s"} (${yours}) count${rows.length === 1 ? "s" : ""} with a constant taken from the middle of the level.`,
          );
        } else setError(e.status === 404 ? `Nothing in the chart database matches "${title}".` : e.message);
      })
      .finally(() => {
        if (mine === opening.current) setBusy(false);
      });
  };

  // a title handed over from another tab, or from the address bar
  useEffect(() => {
    if (!target) return;
    const stamp = `${target.title}|${target.cover ?? ""}|${target.type ?? ""}|${target.difficulty ?? ""}`;
    if (opened.current === stamp && song) return;     // the same chart again while it is on show; once it is left, a repeat opens it
    opened.current = stamp;
    open(target.title, target.type, target.difficulty, target.cover);
  }, [target]); // eslint-disable-line react-hooks/exhaustive-deps

  const [searchError, setSearchError] = useState("");
  const search = (text: string) => {
    setQuery(text);
    opening.current++;      // a lookup still in flight belongs to the old query
    setSong(null);          // a new search is a new page: whatever chart was open goes with the old query
    setError("");
    setBusy(false);
    if (timer.current) window.clearTimeout(timer.current);
    const wanted = text.trim();
    if (wanted.length < 1) {
      setHits(null);
      return;
    }
    timer.current = window.setTimeout(() => {
      timer.current = null;
      searchNow(wanted)
        .then((d) => {
          setSearchError("");
          setHits(d.songs);
        })
        .catch((e: Error) => {
          setSearchError(e.message);
          setHits([]);
        });
    }, 220);
  };

  const chart = song?.charts[selected];
  return (
    <div className="lookup">
      <div className="search-row">
        <input
          className="search"
          type="search"
          placeholder="title, artist or charter"
          value={query}
          onChange={(e) => search(e.target.value)}
          onKeyDown={(e) => {
            if (e.key !== "Enter" || !query.trim()) return;
            const wanted = query.trim();
            if (timer.current) {
              // typed and entered inside the debounce: the hits on hand belong to an earlier query
              window.clearTimeout(timer.current);
              timer.current = null;
              searchNow(wanted)
                .then((d) => open(d.songs[0]?.title ?? wanted))
                .catch(() => open(wanted));
              return;
            }
            open(hits?.[0]?.title ?? wanted);
          }}
          aria-label="Search for a song"
          autoComplete="off"
        />
      </div>
      {hits !== null && (
        <ul className="hits">
          {hits.length === 0 && <li className="empty">{searchError ? `The search could not run. ${searchError}` : "Nothing matches. Try part of the title, its reading in romaji, or an artist or charter."}</li>}
          {hits.map((h) => (
            <li key={h.title} className="hit">
              <Jacket cover={h.cover} size={44} />
              <button type="button" className="hit-title" onClick={() => open(h.title)}>
                {h.title}
                {h.alias ? <span className="alias">{h.alias}</span> : null}
                <small>
                  {h.artist}
                  {h.charters?.length ? <span className="charter">charted by {h.charters.join(", ")}</span> : null}
                </small>
              </button>
              <div className="hit-charts">
                {h.charts.map((c) => (
                  <button
                    key={`${c.chart_type}|${c.difficulty}`}
                    type="button"
                    onClick={() => open(h.title, c.chart_type, c.difficulty)}
                    title={c.played ? `${pct(c.accuracy)} ${c.rank}` : "never played"}
                  >
                    <span className={c.played ? "" : "faded"} style={{ display: "contents" }}>
                      <Chip difficulty={c.difficulty} level={c.level} type={c.chart_type} />
                    </span>
                  </button>
                ))}
              </div>
            </li>
          ))}
        </ul>
      )}
      {busy && <Empty>Looking it up…</Empty>}
      {error && <Empty>{error}</Empty>}
      {!busy && !song && hits === null && !error && (
        <Empty>
          Type a song title. You get every chart the song has, your score on it, what the model expects of you, what each rank is worth to your
          best-50 and the odds of it, what the chart asks of you, your score history on the chart and the chart video. Any title on the other
          tabs opens here too.
        </Empty>
      )}
      {!song && hits === null && (
        <PatternBrowser
          onOpen={(title, type, difficulty) => {
            open(title, type, difficulty);
          }}
          open={browseOpen}
          setOpen={setBrowseOpen}
          tag={browseTag}
          setTag={setBrowseTag}
        />
      )}
      {song && chart && !busy && <Detail song={song} chart={chart} selected={selected} onSelect={setSelected} onTrait={browseTrait} />}
    </div>
  );
}
