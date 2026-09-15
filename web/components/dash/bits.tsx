import { useEffect, useRef, useState } from "react";

const TIER: Record<string, string> = {
  basic: "BASIC",
  advanced: "ADVANCED",
  expert: "EXPERT",
  master: "MASTER",
  remaster: "Re:MASTER",
  utage: "UTAGE",
};

export function Chip({ difficulty, level, constant, type }: { difficulty: string; level?: string; constant?: number; type?: string }) {
  const key = (difficulty || "master").toLowerCase();
  return (
    <span className={`chip chip-${key}`}>
      {TIER[key] ?? key.toUpperCase()}
      {level ? <b>{level}</b> : null}
      {constant ? <em title="chart constant">{constant.toFixed(1)}</em> : null}
      {type ? <i>{type.toUpperCase()}</i> : null}
    </span>
  );
}

export function Jacket({ cover, size = 40 }: { cover: string; size?: number }) {
  const file = (cover || "").split("/").pop()?.split("?")[0] ?? "";
  if (!file) return <span className="jacket empty" style={{ width: size, height: size }} />;
  return <img className="jacket" src={`/api/jacket/${encodeURIComponent(file)}`} width={size} height={size} alt="" loading="lazy" />;
}

export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(digits)}%`;
}

export function num(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return value.toLocaleString("en-US");
}

export function when(iso: string | null | undefined): string {
  if (!iso) return "never";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function day(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function ago(iso: string | null | undefined): string {
  if (!iso) return "never";
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const minutes = Math.round((Date.now() - then) / 60000);
  if (minutes < 2) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 48) return `${hours} h ago`;
  return `${Math.round(hours / 24)} days ago`;
}

export function Lamp({ fc, fs }: { fc: string; fs: string }) {
  const marks: string[] = [];
  if (fc && fc !== "NONE") marks.push(fc);
  if (fs && fs !== "NONE") marks.push(fs);
  if (!marks.length) return <span className="dim">—</span>;
  return <span className="lamp-text">{marks.join(" · ")}</span>;
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <p className="empty">{children}</p>;
}

/** What a section shows when its data could not be fetched: the reason, and a way to try again. Never the empty-state copy. */
export function LoadError({ what, message, onRetry }: { what: string; message: string; onRetry?: () => void }) {
  return (
    <p className="empty error" role="alert">
      Couldn&apos;t load {what}. {message}
      {onRetry ? (
        <>
          {" "}
          <button type="button" className="linkish" onClick={onRetry}>
            try again
          </button>
        </>
      ) : null}
    </p>
  );
}

/** "3 days ago" that reveals the exact moment on hover and to assistive tech. */
export function Ago({ iso, prefix = "" }: { iso: string | null | undefined; prefix?: string }) {
  if (!iso) return <>{prefix}never</>;
  return (
    <time dateTime={iso} title={when(iso)}>
      {prefix}
      {ago(iso)}
    </time>
  );
}

/** A small circled i that opens a short explanation of the section it sits beside. */
export function Info({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLSpanElement>(null);
  useEffect(() => {
    if (!open) return;
    const away = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const key = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", away);
    document.addEventListener("keydown", key);
    return () => {
      document.removeEventListener("mousedown", away);
      document.removeEventListener("keydown", key);
    };
  }, [open]);
  return (
    <span className={`info${open ? " open" : ""}`} ref={box}>
      <button type="button" className="info-btn" aria-label="what this is" aria-expanded={open} onClick={() => setOpen(!open)}>
        i
      </button>
      {open && (
        <span className="info-pop" role="tooltip">
          {text}
        </span>
      )}
    </span>
  );
}

export function Label({ children, info }: { children: React.ReactNode; info?: string }) {
  return (
    <div className="label">
      {children}
      {info ? <Info text={info} /> : null}
    </div>
  );
}

export type OpenChart = (title: string, type: string, difficulty: string) => void;

/** A chart title that opens the chart in the Look up tab. */
export function TitleLink({ title, type, difficulty, onOpen }: { title: string; type: string; difficulty: string; onOpen?: OpenChart }) {
  if (!onOpen) return <span className="title">{title}</span>;
  return (
    <button type="button" className="title title-link" onClick={() => onOpen(title, type, difficulty)}>
      {title}
    </button>
  );
}

export type ImageKind = "analyze" | "profile" | "new" | "traits" | "progress" | "best50" | "recent";

const IMAGE_LABEL: Record<ImageKind, string> = {
  analyze: "what to play",
  profile: "play profile",
  new: "new charts",
  traits: "traits",
  progress: "rating over time",
  best50: "best 50",
  recent: "recent plays",
};

/** Saves the picture the matching Discord command draws. Rendering takes a moment, so it says so. */
export function SaveImage({ kind }: { kind: ImageKind }) {
  const [state, setState] = useState<"" | "busy" | "empty" | "failed">("");

  const save = async () => {
    setState("busy");
    try {
      const answer = await fetch(`/api/me/image?kind=${encodeURIComponent(kind)}`, { credentials: "same-origin" });
      // 404 here means the bot had nothing to draw yet, which is not the same as a failure
      if (answer.status === 404) {
        setState("empty");
        return;
      }
      if (!answer.ok) throw new Error(String(answer.status));
      const blob = await answer.blob();
      const href = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = href;
      link.download = `rasmai-${kind}.png`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      // the browser needs the address to outlive the click, not the call
      setTimeout(() => URL.revokeObjectURL(href), 10_000);
      setState("");
    } catch {
      setState("failed");
    }
  };

  return (
    <button type="button" className="save-image" onClick={save} disabled={state === "busy"}
            title={`Save the ${IMAGE_LABEL[kind]} image, the one the bot posts in Discord`}>
      {state === "busy" ? "drawing…"
        : state === "empty" ? "nothing to draw yet"
        : state === "failed" ? "could not draw it"
        : `save ${IMAGE_LABEL[kind]}`}
    </button>
  );
}
