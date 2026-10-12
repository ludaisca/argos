export interface Target {
  type: string;
  value?: string;
  limit?: number;
  kind?: string;
  details?: boolean;
}

export interface Brief {
  source?: string;
  job: string;
  objective: string;
  questions: string[];
  targets: Target[];
  max_targets: number;
  platforms: string[];
}

export interface SessionInfo {
  cookies: number;
  profile: boolean;
}

export interface QuotaInfo {
  used: number;
  daily_limit: number;
  remaining: number;
  per_minute: number;
}

export interface RunSummary {
  name: string;
  job: string;
  objective: string;
  plan_source?: string | null;
  platforms?: string[] | null;
  generated_at?: string | null;
  ok: number;
  total: number;
  analysis: boolean;
}

export interface StatusPayload {
  home: string;
  llm: {
    llm_configured: boolean;
    llm_key_set: boolean;
    llm_key_masked?: string | null;
    llm_key_source?: string | null;
    llm_base_url: string;
    llm_model: string;
  };
  interval_hours: number;
  sessions: Record<string, SessionInfo>;
  quota: Record<string, QuotaInfo>;
  jobs: { pending: number; done: number; failed: number };
  runs: RunSummary[];
  brief: Partial<Brief> & { source?: string };
  daemon: boolean;
  busy: boolean;
}

export interface Settings {
  llm_configured: boolean;
  llm_key_set: boolean;
  llm_key_masked?: string | null;
  llm_key_source?: string | null;
  llm_base_url: string;
  llm_model: string;
  interval_hours: number;
}

export interface ProcRecord {
  id: string;
  kind: string;
  label: string;
  status: "running" | "ok" | "error" | "stopped";
  started_at: string;
  finished_at?: string | null;
  exit_code?: number | null;
  result?: {
    run_dir?: string;
    job_dir?: string;
    analysis?: string | null;
    plan_source?: string;
    plan?: Target[];
    results?: { target: string; status: string }[];
    run_name?: string;
  } | null;
  log: string;
}

export interface JobEntry {
  file: string;
  job?: string;
  objective?: string;
  platforms?: string[];
  error?: string;
}

export interface JobsPayload {
  dir: string;
  pending: JobEntry[];
  done: string[];
  failed: string[];
}

export interface Meta {
  home: string;
  jobs_dir: string;
  runs_dir: string;
  platforms: string[];
  platform_labels: Record<string, string>;
  target_types: Record<string, string[]>;
  kinds: Record<string, string[]>;
  max_targets_cap: number;
  target_limit_cap: number;
}

export interface Place {
  source: string;
  id: string;
  name: string;
  category?: string | null;
  address?: string | null;
  phone?: string | null;
  website?: string | null;
  opening_hours?: string | null;
  lat?: number | null;
  lon?: number | null;
  rating?: number | null;
  reviews?: number | null;
  distance_km?: number | null;
  url?: string | null;
  query?: string | null;
  location?: string | null;
}

export interface PlacesSearchResult {
  provider: string;
  detail: string;
  places: Place[];
  center: { lat: number; lon: number; label: string } | null;
}

export interface RunFile {
  path: string;
  size: number;
}

export interface RunDetail {
  name: string;
  meta: {
    job?: string;
    objective?: string;
    plan_source?: string;
    platforms?: string[];
    generated_at?: string;
    results?: { target: string; status: string; written?: Record<string, number> }[];
  };
  analysis?: string | null;
  files: RunFile[];
}

export interface DoctorResult {
  generated_at: string;
  browser: { ready: boolean; detail: string };
  platforms: Record<string, { name?: string; status?: string; detail?: string; hint?: string | null }>;
}

export type Section = "dashboard" | "brief" | "places" | "run" | "results" | "settings";
