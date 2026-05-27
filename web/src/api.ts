const API_BASE = import.meta.env.VITE_API_BASE ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(typeof err.detail === "string" ? err.detail : JSON.stringify(err.detail));
  }
  if (res.status === 204) {
    return undefined as T;
  }
  return res.json() as Promise<T>;
}

export type Health = {
  status: string;
  dict_data: string;
  output: string;
  word_count: number;
};

export type KeywordSeed = {
  id: number;
  keyword: string;
  purpose_of_keyword: string;
  is_regex: boolean;
  ontology_relation: string;
};

export type WordEdit = {
  word: string;
  meaning: string;
  synonyms: string[];
  antonyms: string[];
  pos: string;
  register: string;
  domain: string;
  risk_level: number | null;
  tags: string[];
  source_file: string;
};

export type CategoryEdit = {
  category_name: string;
  parent_category: string;
  category_level: number;
  default_risk_level: number | null;
  override_risk_level: number | null;
  has_override: boolean;
};

export type BulkApplyResponse = {
  updated: number;
  skipped: number;
  missing: number;
  total_targets: number;
};

export type ConvertJob = {
  job_id: string;
  status: string;
  percent: number;
  phase: string;
  current: number;
  total: number;
  files: Record<string, string>;
  error: string;
  created_at: string;
  updated_at: string;
};

export type ConvertStartResult =
  | {
      kind: "async";
      job_id: string;
      status: string;
      percent: number;
      phase: string;
      current: number;
      total: number;
    }
  | {
      kind: "sync";
      files: Record<string, string>;
    };

function readConvertJobId(body: Record<string, unknown>): string {
  const raw = body.job_id ?? body.jobId;
  return typeof raw === "string" ? raw.trim() : "";
}

export const api = {
  health: () => request<Health>("/api/v1/health"),
  tiers: () => request<Record<string, number[]>>("/api/v1/meta/tiers"),
  keywordSeeds: () => request<KeywordSeed[]>("/api/v1/meta/keywords"),
  createKeywordSeed: (body: Omit<KeywordSeed, "id"> & { id?: number }) =>
    request<KeywordSeed>("/api/v1/meta/keywords", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  updateKeywordSeed: (id: number, body: Omit<KeywordSeed, "id">) =>
    request<KeywordSeed>(`/api/v1/meta/keywords/${id}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  deleteKeywordSeed: (id: number) =>
    request<void>(`/api/v1/meta/keywords/${id}`, { method: "DELETE" }),
  startConvert: async () => {
    const body = await request<Record<string, unknown>>("/api/v1/convert", { method: "POST" });
    const jobId = readConvertJobId(body);
    if (jobId) {
      return {
        kind: "async" as const,
        job_id: jobId,
        status: String(body.status ?? "queued"),
        percent: Number(body.percent ?? 0),
        phase: String(body.phase ?? "queued"),
        current: Number(body.current ?? 0),
        total: Number(body.total ?? 1),
      };
    }
    if (body.files && typeof body.files === "object") {
      return {
        kind: "sync" as const,
        files: body.files as Record<string, string>,
      };
    }
    throw new Error(
      "Convert API returned an unexpected response. Restart the backend with `uvicorn safety_api.main:app --reload --port 8000` and try again.",
    );
  },
  getConvertJob: (jobId: string) => request<ConvertJob>(`/api/v1/convert/${encodeURIComponent(jobId)}`),
  searchWords: (params: Record<string, string>) => {
    const q = new URLSearchParams(params);
    return request<Record<string, unknown>[]>(`/api/v1/search/words?${q}`);
  },
  searchCategories: (query: string, subtree = "") => {
    const q = new URLSearchParams({ query, subtree });
    return request<Record<string, unknown>[]>(`/api/v1/search/categories?${q}`);
  },
  categoryTree: (root = "lexicon") =>
    request<Record<string, unknown>[]>(`/api/v1/search/category-tree?root=${encodeURIComponent(root)}`),
  wordPairs: (word: string) =>
    request<Record<string, unknown>[]>(`/api/v1/search/word-pairs?word=${encodeURIComponent(word)}`),
  wordsInCategory: (category: string, exact = true) =>
    request<Record<string, unknown>[]>(
      `/api/v1/search/words/in-category?category=${encodeURIComponent(category)}&exact=${exact ? "true" : "false"}`,
    ),
  getWord: (token: string) =>
    request<Record<string, unknown>>(`/api/v1/words/${encodeURIComponent(token)}`),
  getWordEdit: (token: string) =>
    request<WordEdit>(`/api/v1/edit/words/${encodeURIComponent(token)}`),
  updateWordEdit: (
    token: string,
    body: Omit<WordEdit, "word" | "source_file">,
  ) =>
    request<WordEdit>(`/api/v1/edit/words/${encodeURIComponent(token)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  getCategoryEdit: (category: string) =>
    request<CategoryEdit>(`/api/v1/edit/categories/${encodeURIComponent(category)}`),
  updateCategoryEdit: (category: string, default_risk_level: number | null) =>
    request<CategoryEdit>(`/api/v1/edit/categories/${encodeURIComponent(category)}`, {
      method: "PUT",
      body: JSON.stringify({ default_risk_level }),
    }),
  applyDirect: (body: {
    entity_type: string;
    entity_key: string;
    score: number;
    reason: string;
    actor?: string;
  }) =>
    request<Record<string, unknown>>("/api/v1/safety/apply", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  audit: (limit = 50) => request<Record<string, unknown>[]>(`/api/v1/safety/audit?limit=${limit}`),
  applyWordScoreToSynonyms: (body: { word: string; score: number; reason?: string; actor?: string }) =>
    request<BulkApplyResponse>("/api/v1/safety/bulk/synonyms", {
      method: "POST",
      body: JSON.stringify(body),
    }),
  applyCategoryScoreToWords: (body: {
    category: string;
    score: number;
    reason?: string;
    actor?: string;
  }) =>
    request<BulkApplyResponse>("/api/v1/safety/bulk/category-words", {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
