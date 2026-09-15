export type DiscordUser = { id: string; name: string; handle: string; avatar: string };

export type HistoryPoint = {
  recordedAt: string;
  rating: number;
  best50: number;
  newTotal: number;
  oldTotal: number;
  charts: number;
  plays: number;
};

export type RefreshStatus = {
  running: boolean;
  stage?: string;
  done?: number;
  total?: number;
  detail?: string;
  error?: string;
  finishedAt?: string;
};

export type Sharing = {
  on: boolean;
  url: string;
  sections: { best50: boolean; traits: boolean; recent: boolean; areas: boolean };
};

export type Overview = {
  user: DiscordUser;
  linked: boolean;
  oauth: boolean;
  region?: string;
  profile?: { name: string; rating: number; dan: string; title: string; totalPlayCount: number; updatedAt: string };
  snapshot?: { recordedAt: string; best50: number; newTotal: number; oldTotal: number; charts: number };
  history?: HistoryPoint[];
  settings?: Record<string, string | boolean>;
  refresh?: RefreshStatus;
  sessionExpired?: string;
  admin?: boolean;
  sharing?: Sharing;
  playHistory?: number;
  judgements?: JudgementProfileData | null;
  sinceLast?: { since: string; ratingDelta: number; plays: number; newBests: number } | null;
  analysis?: {
    profile?: {
      comfortConstant: number;
      curve?: { c: number; e: number; s: number }[];
      reachConstant: number;
      hardestS: number;
      playedCeiling?: number;
      sampleSize?: number;
      habits?: {
        age?: { plays: number; medianYears: number; freshShare: number; newestQuarterYears: number };
        rerates?: { charts: number; rating: number };
        notes?: { notes: number; charts: number };
      };
      traits?: Trait[];
      traitAxes?: Trait[];
      [key: string]: unknown;
    };
    traitPractice?: TraitPractice[];
    best50?: {
      total: number;
      newTotal: number;
      oldTotal: number;
      newCutoff: number;
      oldCutoff: number;
      newSlotsOpen: number;
      oldSlotsOpen: number;
    };
    reachableGain?: number;
  };
};

export type JudgementProfileData = {
  plays: number;
  types: { kind: string; notes: number; share: number; lossShare: number; per100: number; clean: number; tilt: number }[];
  weak: string | null;
  fast: number;
  late: number;
  lateShare: number | null;
  lostPerPlay: number;
};

export type ChartRow = {
  title: string;
  type: string;
  difficulty: string;
  level: string;
  constant: number;
  accuracy: number;
  rank: string;
  rating: number;
  fc: string;
  fs: string;
  dx: number;
  maxDx: number;
  new: boolean;
  plays: number;
  cover: string;
  genre: string;
  artist: string;
  inBest50: boolean;
  estimated?: boolean;
};

export type Recommendation = {
  song: string;
  difficulty: number;
  current_accuracy: number;
  target_accuracy: number;
  current_rating: number;
  target_rating: number;
  potential_gain: number;
  current_rank: string;
  target_rank: string;
  level: string;
  cover_url: string;
  chart_type: string;
  difficulty_type: string;
  category: string;
  plays: number;
  expected: number;
  estimated?: boolean;
  feasibility: number;
  is_new: boolean;
  is_unplayed?: boolean;
  value_chart_reason?: string;
  required_accuracy: number;
};

export type PlanStep = {
  option: {
    title: string;
    chart_type: string;
    difficulty_type: string;
    level: string;
    constant: number;
    cover: string;
    is_new: boolean;
    is_unplayed: boolean;
    current_accuracy: number;
    current_rank: string;
    target_accuracy: number;
    target_rank: string;
    target_rating: number;
    feasibility: number;
    plays: number;
  };
  gain: number;
  cumulative: number;
};

export type NewPick = {
  title: string;
  chart_type: string;
  difficulty: string;
  level: string;
  constant: number;
  genre: string;
  cover: string;
  is_new: boolean;
  expected_accuracy: number;
  expected_rank: string;
  expected_rating: number;
  rating_gain: number;
  odds_of_s: number;
};

export type Picks = {
  challenge: string;
  label: string;
  level?: string;
  scope?: string;
  recommendations: Recommendation[];
  summary: { reachableGain?: number; ratingMoves?: number; fallbackFrom?: string; [key: string]: unknown } | null;
  plan: {
    goal: number;
    start: number;
    needed: number;
    total: number;
    reached: boolean;
    shortfall: number;
    averageStretch: number;
    fallbackFrom: string | null;
    steps: PlanStep[];
  };
  newCharts: NewPick[];
  newWindow: [number, number];
};

export type PlayDetail = {
  fast: number;
  late: number;
  combo: number;
  max_combo: number;
  sync: number;
  max_sync: number;
  achievement: number;
  notes: Record<string, { critical: number; perfect: number; great: number; good: number; miss: number }>;
  lost: Record<string, number>;
};

export type RecentPlay = {
  position: number;
  idx?: string;
  title: string;
  difficulty: string;
  chart_type: string;
  level: string;
  constant?: number;
  achievement: number | null;
  rank: string;
  dx: number;
  max_dx: number;
  fc: string;
  fs: string;
  track: number | string;
  time: string;
  day: string;
  chart_rating: number;
  pb: boolean;
  in_b50: boolean;
  cover: string;
};

export type AreaEntry = {
  name: string;
  kind: "area" | "event";
  distance: number;
  state: "not_started" | "in_progress" | "completed" | "ended";
  stateLabel: string;
  toGo: number | null;
  milestone: number | null;
  playsToGo: number | null;
  pace: number | null;
  ownPace: boolean;
  image: string;
  imageKey: string;
  english: string;
  chinese: string;
  version: string;
  addedAsia: string;
  rewards: AreaReward[];
  nextReward: (AreaReward & { toGo: number }) | null;
  firstGift: AreaReward | null;
  nextRewards: AreaReward[];
  periodStart: string | null;
  periodEnd: string | null;
  since: string | null;
  gained: number;
};

export type AreaReward = { total: number; kind: string; name: string; reached: boolean; playsToGo: number | null };

export type AreaSummary = {
  areas: AreaEntry[];
  events: AreaEntry[];
  ended: AreaEntry[];
  pace: number | null;
  readings: number;
  readAt: string | null;
  counts: { travelling: number; completed: number; untouched: number; ended: number };
};

export type LookupTarget = { title: string; cover?: string; type?: string; difficulty?: string };

export type PatternTag = { tag: string; label: string; english: string; charts: number; community: boolean; dimension: string };
export type PatternChart = {
  title: string;
  chart_type: string;
  difficulty: string;
  level: string;
  constant: number;
  cover: string;
  played: boolean;
  accuracy: number | null;
  rank: string;
  rating: number;
  note: string;
  tags: string[];
};
export type PatternBrowse = { tags: PatternTag[]; tag: string; english: string; level: string; difficulty: string; charts: PatternChart[] };

export type UnlockArea = { line: number; name: string; title: string; distance: number; state: string; milestone: number | null };

export type SearchHit = {
  title: string;
  alias: string;
  artist: string;
  genre: string;
  cover: string;
  charters: string[];
  charts: { chart_type: string; difficulty: string; level: string; constant: number; played: boolean; accuracy: number | null; rank: string }[];
};

export type LadderStep = { rank: string; need: number; rating: number; gain: number; odds: number };

export type ChartDetail = {
  title: string;
  chart_type: string;
  difficulty: string;
  level: string;
  constant: number;
  notes: number;
  version: number;
  intl: boolean;
  deleted: boolean;
  designer: string;
  is_new: boolean;
  played: boolean;
  note: string;
  accuracy?: number;
  rank?: string;
  rating?: number;
  fc?: string;
  fs?: string;
  dx?: number;
  max_dx?: number;
  stars?: number;
  plays?: number;
  usual: number | null;
  prediction: { expected: number; sigma: number; rank: string; low: number; high: number; new_best: number | null; plays: number; tier_offset: number; tier: string } | null;
  ladder: LadderStep[];
  history: { when: string; achievement: number; dx: number; fc: string; fs: string; source: string; constant: number; rating: number }[];
  video: string | null;
  youtube: string;
  noteSplit: Record<string, number> | null;
  released: string;
  patterns: ChartPattern[];
};

export type ChartPattern = { key: string; label: string; dimension: string; community: boolean; offset: number | null };

export type Trait = { dimension: string; label: string; english?: string; offset: number; count: number; plays?: number; verified?: boolean; leaning?: boolean; p?: number };
export type PracticeChart = { title: string; chart_type: string; difficulty: string; level: string; constant: number; cover: string; accuracy: number | null };
export type TraitPractice = { label: string; english: string; tag: string; verified: boolean; offset: number; count: number; charts: PracticeChart[] };

export type SongLookup = {
  title: string;
  alias: string;
  artist: string;
  genre: string;
  cover: string;
  bpm: string;
  reading: string;
  version: string;
  selected: number;
  charts: ChartDetail[];
};

/** The codes the site's API answers with, as sentences a person can act on. */
const ERROR_TEXT: Record<string, string> = {
  bot_unreachable: "The bot is not reachable right now. It may be restarting; try again in a minute.",
  rate_limited: "Too many requests in a short time. Wait a moment and try again.",
  signed_out: "Your sign-in has expired. Sign in again to continue.",
  bad_response: "The server's answer could not be read.",
  not_linked: "No maimai account is linked to this Discord account yet.",
};

export function describeError(status: number, body: Record<string, unknown>): string {
  const code = String(body.error ?? "");
  if (ERROR_TEXT[code]) return ERROR_TEXT[code];
  if (typeof body.message === "string" && body.message) return body.message;
  if (status === 502 || status === 503 || status === 504) return ERROR_TEXT.bot_unreachable;
  if (status === 429) return ERROR_TEXT.rate_limited;
  if (status === 401) return ERROR_TEXT.signed_out;
  if (status === 404) return "That was not found.";
  if (status >= 500) return "The server hit a problem. Try again in a moment.";
  if (status === 0) return "The network request did not go through. Check the connection and try again.";
  return code ? code.replace(/_/g, " ") : `Something went wrong (${status}).`;
}

export class ApiError extends Error {
  status: number;
  body: Record<string, unknown>;
  code: string;
  constructor(status: number, body: Record<string, unknown>) {
    super(describeError(status, body));
    this.status = status;
    this.body = body;
    this.code = String(body.error ?? "");
  }
}

export const SIGNED_OUT_EVENT = "rasmai:signed-out";

/** A 401 from any call means the session is gone; the dashboard listens for this and shows the sign-in gate. */
function announceSignedOut(body: Record<string, unknown>) {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent(SIGNED_OUT_EVENT, { detail: body }));
}

async function fetchJSON<T>(path: string, init: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(path, { credentials: "same-origin", ...init, headers: { Accept: "application/json", ...(init.headers ?? {}) } });
  } catch {
    throw new ApiError(0, { error: "network" });
  }
  if (r.status === 204) return {} as T;
  let body: Record<string, unknown> | null = null;
  try {
    body = (await r.json()) as Record<string, unknown>;
  } catch {
    body = null;
  }
  if (r.status === 401) announceSignedOut(body ?? {});
  if (!r.ok) throw new ApiError(r.status, body ?? {});
  if (body === null) throw new ApiError(r.status, { error: "bad_response" });
  return body as T;
}

export async function getJSON<T>(path: string): Promise<T> {
  return fetchJSON<T>(path, {});
}

export async function postJSON<T>(path: string, body?: unknown): Promise<T> {
  return fetchJSON<T>(path, body === undefined ? { method: "POST" } : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
}
