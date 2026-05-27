import { Dispatch, ReactNode, SetStateAction, useCallback, useEffect, useState } from "react";
import { api, CategoryEdit, Health, KeywordSeed, WordEdit } from "./api";

type Tab = "search" | "convert" | "safety" | "tree" | "keywords" | "edit";
type EditSelection =
  | { kind: "word"; key: string; requestId: number }
  | { kind: "category"; key: string; requestId: number };
type SearchMode = "words" | "categories" | "pairs";
type SearchState = {
  query: string;
  tier: string;
  domain: string;
  category: string;
  pairWord: string;
  anchorWord: string;
  includeSynonyms: boolean;
  includeAntonyms: boolean;
  includeSameDomain: boolean;
  rows: Record<string, unknown>[];
  mode: SearchMode;
};

const defaultSearchState = (): SearchState => ({
  query: "",
  tier: "",
  domain: "",
  category: "",
  pairWord: "",
  anchorWord: "",
  includeSynonyms: false,
  includeAntonyms: false,
  includeSameDomain: false,
  rows: [],
  mode: "words",
});

function scoreColor(level: number | string | null | undefined): string {
  const n = typeof level === "number" ? level : parseFloat(String(level ?? "0"));
  if (Number.isNaN(n) || n === 0) return "#9e9e9e";
  if (n >= 0.8) return "#c62828";
  if (n >= 0.6) return "#ef6c00";
  if (n >= 0.4) return "#f9a825";
  return "#558b2f";
}

type DataTableColumn = {
  key: string;
  header?: string;
  render?: (row: Record<string, unknown>) => ReactNode;
};

const HIDDEN_WORD_FIELDS = new Set(["primary_category", "secondary_category", "meaning"]);

function sanitizeWordRow(row: Record<string, unknown>): Record<string, unknown> {
  const next = { ...row };
  delete next.primary_category;
  delete next.secondary_category;
  return next;
}

function DataTable({
  rows,
  onRowClick,
  columns,
}: {
  rows: Record<string, unknown>[];
  onRowClick?: (row: Record<string, unknown>) => void;
  columns?: DataTableColumn[];
}) {
  if (rows.length === 0) return <p>No results.</p>;
  const cols: DataTableColumn[] =
    columns && columns.length > 0
      ? columns
      : Object.keys(rows[0]).map((key) => ({ key, header: key }));
  return (
    <table>
      <thead>
        <tr>
          {cols.map((c) => (
            <th key={c.key}>{c.header ?? c.key}</th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((row, i) => (
          <tr
            key={i}
            onClick={() => onRowClick?.(row)}
            style={onRowClick ? { cursor: "pointer" } : undefined}
          >
            {cols.map((c) => (
              <td key={c.key}>
                {c.render ? (
                  c.render(row)
                ) : c.key.includes("risk") || c.key.includes("score") || c.key.includes("level") ? (
                  <span className="score-cell">
                    <span style={{ color: scoreColor(row[c.key] as number) }}>
                      {String(row[c.key] ?? "")}
                    </span>
                    {row[c.key] !== "" && row[c.key] != null && (
                      <span
                        className="score-bar"
                        style={{
                          width: `${Math.min(100, Number(row[c.key]) * 100)}px`,
                          opacity: 0.7,
                        }}
                      />
                    )}
                  </span>
                ) : (
                  String(row[c.key] ?? "")
                )}
              </td>
            ))}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function App() {
  const [tab, setTab] = useState<Tab>("search");
  const [health, setHealth] = useState<Health | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [loading, setLoading] = useState(false);
  const [convertRunning, setConvertRunning] = useState(false);
  const [convertStartedAtMs, setConvertStartedAtMs] = useState<number | null>(null);
  const [convertLastAdvanceAtMs, setConvertLastAdvanceAtMs] = useState<number | null>(null);
  const [convertProgress, setConvertProgress] = useState<{
    percent: number;
    phase: string;
    current: number;
    total: number;
  } | null>(null);
  const [editSelection, setEditSelection] = useState<EditSelection | null>(null);
  const [searchState, setSearchState] = useState<SearchState>(defaultSearchState);
  const [isEditModalOpen, setIsEditModalOpen] = useState(false);
  const [refreshActiveTable, setRefreshActiveTable] = useState<(() => Promise<void>) | null>(null);

  const refreshHealth = useCallback(async () => {
    try {
      setHealth(await api.health());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    refreshHealth();
  }, [refreshHealth]);

  const run = async (fn: () => Promise<void>) => {
    setError("");
    setMessage("");
    setLoading(true);
    try {
      await fn();
      await refreshHealth();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  const openEditTool = (kind: "word" | "category", key: string) => {
    setEditSelection({ kind, key, requestId: Date.now() });
    setIsEditModalOpen(true);
  };

  const refreshVisibleTable = useCallback(async () => {
    if (!refreshActiveTable) return;
    await refreshActiveTable();
  }, [refreshActiveTable]);

  return (
    <div className="app">
      <header>
        <h1>SafetyChecker</h1>
        {health && (
          <span className="health-badge">
            {health.word_count} words indexed
          </span>
        )}
      </header>

      <nav className="tabs">
        {(["search", "tree", "edit", "convert", "keywords", "safety"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t === "search"
              ? "Search"
              : t === "tree"
                ? "Category tree"
                : t === "convert"
                  ? "Convert"
                  : t === "keywords"
                    ? "Keyword seeds"
                    : t === "edit"
                      ? "Edit tools"
                    : "Safety scores"}
          </button>
        ))}
      </nav>

      {error && <p className="error">{error}</p>}
      {message && <p className="message">{message}</p>}

      {tab === "convert" && (
        <ConvertPanel
          loading={loading}
          running={convertRunning}
          progress={convertProgress}
          startedAtMs={convertStartedAtMs}
          lastAdvanceAtMs={convertLastAdvanceAtMs}
          onConvert={() =>
            run(async () => {
              setConvertRunning(true);
              const startedAt = Date.now();
              setConvertStartedAtMs(startedAt);
              setConvertLastAdvanceAtMs(startedAt);
              try {
                setConvertProgress({ percent: 0, phase: "queued", current: 0, total: 1 });
                const started = await api.startConvert();
                if (started.kind === "sync") {
                  setConvertLastAdvanceAtMs(Date.now());
                  setConvertProgress({ percent: 100, phase: "done", current: 1, total: 1 });
                  setMessage(`Converted ${Object.keys(started.files).length} CSV files.`);
                  window.setTimeout(() => setConvertProgress(null), 2600);
                  return;
                }

                let status = await api.getConvertJob(started.job_id);
                let lastPercent = started.percent;
                setConvertProgress({
                  percent: started.percent,
                  phase: started.phase,
                  current: started.current,
                  total: started.total,
                });
                while (status.status === "queued" || status.status === "running") {
                  setConvertProgress({
                    percent: status.percent,
                    phase: status.phase,
                    current: status.current,
                    total: status.total,
                  });
                  if (status.percent > lastPercent) {
                    setConvertLastAdvanceAtMs(Date.now());
                    lastPercent = status.percent;
                  }
                  await new Promise((resolve) => window.setTimeout(resolve, 300));
                  status = await api.getConvertJob(started.job_id);
                }
                if (status.status === "error") {
                  setConvertProgress(null);
                  throw new Error(status.error || "Convert job failed.");
                }
                setConvertLastAdvanceAtMs(Date.now());
                setConvertProgress({
                  percent: status.percent,
                  phase: status.phase,
                  current: status.current,
                  total: status.total,
                });
                setMessage(`Converted ${Object.keys(status.files).length} CSV files.`);
                window.setTimeout(() => setConvertProgress(null), 2600);
              } finally {
                setConvertRunning(false);
              }
            })
          }
        />
      )}
      {tab === "search" && (
        <SearchPanel
          loading={loading}
          onSearch={run}
          onOpenEditor={openEditTool}
          onMessage={setMessage}
          onRegisterRefresh={setRefreshActiveTable}
          state={searchState}
          onStateChange={setSearchState}
        />
      )}
      {tab === "tree" && (
        <TreePanel
          loading={loading}
          onSearch={run}
          onOpenEditor={openEditTool}
          onMessage={setMessage}
          onRegisterRefresh={setRefreshActiveTable}
        />
      )}
      {tab === "keywords" && (
        <KeywordsPanel loading={loading} onAction={run} onMessage={setMessage} />
      )}
      {tab === "edit" && (
        <EditPanel
          loading={loading}
          onAction={run}
          onMessage={setMessage}
          selection={editSelection}
          onAfterSave={refreshVisibleTable}
        />
      )}
      {tab === "safety" && (
        <SafetyPanel
          loading={loading}
          onAction={run}
          onMessage={setMessage}
          refreshHealth={refreshHealth}
        />
      )}
      {isEditModalOpen && (
        <div className="modal-backdrop" onClick={() => setIsEditModalOpen(false)}>
          <div className="modal-panel" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3>Quick edit</h3>
              <button onClick={() => setIsEditModalOpen(false)}>Close</button>
            </div>
            <EditPanel
              loading={loading}
              onAction={run}
              onMessage={setMessage}
              selection={editSelection}
              onAfterSave={refreshVisibleTable}
            />
          </div>
        </div>
      )}
    </div>
  );
}

function EditPanel({
  loading,
  onAction,
  onMessage,
  selection,
  onAfterSave,
}: {
  loading: boolean;
  onAction: (fn: () => Promise<void>) => void;
  onMessage: (m: string) => void;
  selection: EditSelection | null;
  onAfterSave?: () => Promise<void>;
}) {
  const [wordKey, setWordKey] = useState("");
  const [word, setWord] = useState<WordEdit | null>(null);
  const [applyingWordBulk, setApplyingWordBulk] = useState(false);
  const [categoryKey, setCategoryKey] = useState("");
  const [category, setCategory] = useState<CategoryEdit | null>(null);
  const [applyingCategoryBulk, setApplyingCategoryBulk] = useState(false);

  const loadWord = () =>
    onAction(async () => {
      const next = await api.getWordEdit(wordKey.trim());
      setWord(next);
      onMessage(`Loaded word ${next.word}.`);
    });

  const saveWord = () =>
    onAction(async () => {
      if (!word) return;
      const updated = await api.updateWordEdit(word.word, {
        meaning: word.meaning,
        synonyms: word.synonyms,
        antonyms: word.antonyms,
        pos: word.pos,
        register: word.register,
        domain: word.domain,
        risk_level: word.risk_level,
        tags: word.tags,
      });
      setWord(updated);
      onMessage(`Saved word ${updated.word}.`);
      await onAfterSave?.();
    });

  const applyWordScoreToSynonyms = () =>
    onAction(async () => {
      if (!word || word.risk_level == null) return;
      if (!window.confirm(`Apply score ${word.risk_level.toFixed(2)} to all synonyms of ${word.word}?`)) {
        return;
      }
      setApplyingWordBulk(true);
      try {
        const result = await api.applyWordScoreToSynonyms({
          word: word.word,
          score: word.risk_level,
        });
        onMessage(
          `Applied to synonyms: ${result.updated} updated, ${result.skipped} skipped, ${result.missing} missing.`,
        );
        await onAfterSave?.();
      } finally {
        setApplyingWordBulk(false);
      }
    });

  const loadCategory = () =>
    onAction(async () => {
      const next = await api.getCategoryEdit(categoryKey.trim());
      setCategory(next);
      onMessage(`Loaded category ${next.category_name}.`);
    });

  const saveCategory = () =>
    onAction(async () => {
      if (!category) return;
      const updated = await api.updateCategoryEdit(category.category_name, category.override_risk_level);
      setCategory(updated);
      onMessage(`Saved category override for ${updated.category_name}.`);
      await onAfterSave?.();
    });

  const applyCategoryScoreToWords = () =>
    onAction(async () => {
      if (!category) return;
      const score = category.override_risk_level ?? category.default_risk_level;
      if (score == null) return;
      if (!window.confirm(`Apply score ${score.toFixed(2)} to direct words in ${category.category_name}?`)) {
        return;
      }
      setApplyingCategoryBulk(true);
      try {
        const result = await api.applyCategoryScoreToWords({
          category: category.category_name,
          score,
        });
        onMessage(
          `Applied to category words: ${result.updated} updated, ${result.skipped} skipped, ${result.missing} missing.`,
        );
        await onAfterSave?.();
      } finally {
        setApplyingCategoryBulk(false);
      }
    });

  useEffect(() => {
    if (!selection) return;
    if (selection.kind === "word") {
      setWordKey(selection.key);
      onAction(async () => {
        const next = await api.getWordEdit(selection.key.trim());
        setWord(next);
        onMessage(`Loaded word ${next.word} from search result.`);
      });
      return;
    }
    setCategoryKey(selection.key);
    onAction(async () => {
      const next = await api.getCategoryEdit(selection.key.trim());
      setCategory(next);
      onMessage(`Loaded category ${next.category_name} from search result.`);
    });
  }, [selection?.requestId]);

  return (
    <section className="panel">
      <h2>Edit tools</h2>
      <p>Edit source dictionary entries and category risk overrides from API-backed forms.</p>

      <h3>Word editor</h3>
      <div className="form-row">
        <label>
          Word token
          <input value={wordKey} onChange={(e) => setWordKey(e.target.value)} placeholder="attack" />
        </label>
        <button className="primary" disabled={loading || !wordKey.trim()} onClick={loadWord}>
          Load word
        </button>
      </div>
      {word && (
        <>
          <div className="form-row">
            <label className="wide">
              Meaning
              <textarea
                value={word.meaning}
                onChange={(e) => setWord({ ...word, meaning: e.target.value })}
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              POS
              <input value={word.pos} onChange={(e) => setWord({ ...word, pos: e.target.value })} />
            </label>
            <label>
              Register
              <input
                value={word.register}
                onChange={(e) => setWord({ ...word, register: e.target.value })}
              />
            </label>
            <label>
              Domain
              <input value={word.domain} onChange={(e) => setWord({ ...word, domain: e.target.value })} />
            </label>
            <label>
              Risk level
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={word.risk_level ?? ""}
                onChange={(e) =>
                  setWord({
                    ...word,
                    risk_level: e.target.value === "" ? null : parseFloat(e.target.value),
                  })
                }
              />
            </label>
          </div>
          <div className="form-row">
            <label className="wide">
              Synonyms (comma separated)
              <input
                value={word.synonyms.join(", ")}
                onChange={(e) =>
                  setWord({
                    ...word,
                    synonyms: e.target.value
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
            <label className="wide">
              Antonyms (comma separated)
              <input
                value={word.antonyms.join(", ")}
                onChange={(e) =>
                  setWord({
                    ...word,
                    antonyms: e.target.value
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
            <label className="wide">
              Tags (comma separated)
              <input
                value={word.tags.join(", ")}
                onChange={(e) =>
                  setWord({
                    ...word,
                    tags: e.target.value
                      .split(",")
                      .map((item) => item.trim())
                      .filter(Boolean),
                  })
                }
              />
            </label>
          </div>
          <div className="form-row">
            <button className="primary" disabled={loading} onClick={saveWord}>
              Save word
            </button>
            <button
              disabled={
                loading || applyingWordBulk || !word.synonyms.length || word.risk_level == null
              }
              onClick={applyWordScoreToSynonyms}
            >
              Apply safety score to synonyms
            </button>
          </div>
        </>
      )}

      <h3>Category override editor</h3>
      <div className="form-row">
        <label>
          Category name
          <input
            value={categoryKey}
            onChange={(e) => setCategoryKey(e.target.value)}
            placeholder="safe_flowers"
          />
        </label>
        <button className="primary" disabled={loading || !categoryKey.trim()} onClick={loadCategory}>
          Load category
        </button>
      </div>
      {category && (
        <>
          <p>
            Parent: <code>{category.parent_category || "(root)"}</code> · Computed/default:{" "}
            <code>{String(category.default_risk_level ?? "")}</code>
          </p>
          <div className="form-row">
            <label>
              Override risk level (blank to remove)
              <input
                type="number"
                min={0}
                max={1}
                step={0.01}
                value={category.override_risk_level ?? ""}
                onChange={(e) =>
                  setCategory({
                    ...category,
                    override_risk_level: e.target.value === "" ? null : parseFloat(e.target.value),
                  })
                }
              />
            </label>
            <button className="primary" disabled={loading} onClick={saveCategory}>
              Save category override
            </button>
            <button
              disabled={
                loading ||
                applyingCategoryBulk ||
                (category.override_risk_level == null && category.default_risk_level == null)
              }
              onClick={applyCategoryScoreToWords}
            >
              Apply safety score to all words of this category
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function ConvertPanel({
  loading,
  running,
  progress,
  startedAtMs,
  lastAdvanceAtMs,
  onConvert,
}: {
  loading: boolean;
  running: boolean;
  progress: { percent: number; phase: string; current: number; total: number } | null;
  startedAtMs: number | null;
  lastAdvanceAtMs: number | null;
  onConvert: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!running && !progress) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [running, progress]);

  const elapsedMs = startedAtMs == null ? 0 : Math.max(0, now - startedAtMs);
  const elapsedSec = Math.floor(elapsedMs / 1000);
  const stalledMs = lastAdvanceAtMs == null ? 0 : Math.max(0, now - lastAdvanceAtMs);
  const stalled = running && stalledMs >= 4000;

  return (
    <section className="panel">
      <h2>Convert dictionaries → CSV</h2>
      <p>Rebuild ontology CSVs from <code>dictgraph/dict_data/*.txt</code> and seed files.</p>
      <button className="primary" disabled={loading || running} onClick={onConvert}>
        {running ? "Converting..." : "Run convert"}
      </button>
      {progress && (
        <div className="convert-progress-wrap">
          <div className="convert-progress-label">
            <span>{progress.phase.replace(/_/g, " ")}</span>
            <span>{progress.percent}%</span>
          </div>
          <div className="convert-progress-track" role="progressbar" aria-valuenow={progress.percent}>
            <div className="convert-progress-fill" style={{ width: `${progress.percent}%` }} />
          </div>
          <small>
            {progress.current} / {progress.total}
          </small>
          <small>
            {running
              ? `Elapsed ${elapsedSec}s`
              : progress.phase === "done"
                ? `Completed in ${elapsedSec}s`
                : "Waiting for update..."}
          </small>
          {stalled && <small>Still working in this phase...</small>}
        </div>
      )}
    </section>
  );
}

function SearchPanel({
  loading,
  onSearch,
  onOpenEditor,
  onMessage,
  onRegisterRefresh,
  state,
  onStateChange,
}: {
  loading: boolean;
  onSearch: (fn: () => Promise<void>) => void;
  onOpenEditor: (kind: "word" | "category", key: string) => void;
  onMessage: (m: string) => void;
  onRegisterRefresh: Dispatch<SetStateAction<(() => Promise<void>) | null>>;
  state: SearchState;
  onStateChange: Dispatch<SetStateAction<SearchState>>;
}) {
  const {
    query,
    tier,
    domain,
    category,
    pairWord,
    anchorWord,
    includeSynonyms,
    includeAntonyms,
    includeSameDomain,
    rows,
    mode,
  } = state;
  const setQuery = (value: string) => onStateChange((prev) => ({ ...prev, query: value }));
  const setTier = (value: string) => onStateChange((prev) => ({ ...prev, tier: value }));
  const setDomain = (value: string) => onStateChange((prev) => ({ ...prev, domain: value }));
  const setCategory = (value: string) => onStateChange((prev) => ({ ...prev, category: value }));
  const setPairWord = (value: string) => onStateChange((prev) => ({ ...prev, pairWord: value }));
  const setAnchorWord = (value: string) => onStateChange((prev) => ({ ...prev, anchorWord: value }));
  const setIncludeSynonyms = (value: boolean) =>
    onStateChange((prev) => ({ ...prev, includeSynonyms: value }));
  const setIncludeAntonyms = (value: boolean) =>
    onStateChange((prev) => ({ ...prev, includeAntonyms: value }));
  const setIncludeSameDomain = (value: boolean) =>
    onStateChange((prev) => ({ ...prev, includeSameDomain: value }));
  const setRows = (value: Record<string, unknown>[]) =>
    onStateChange((prev) => ({ ...prev, rows: value }));
  const setMode = (value: SearchMode) => onStateChange((prev) => ({ ...prev, mode: value }));

  const fetchRowsForState = useCallback(async (criteria: SearchState) => {
    if (criteria.mode === "words") {
      const rowMap = new Map<string, Record<string, unknown>>();
      const addRows = (items: Record<string, unknown>[]) => {
        for (const item of items) {
          const cleaned = sanitizeWordRow(item);
          const token = String(cleaned.word ?? "").trim().toLowerCase();
          if (token) rowMap.set(token, cleaned);
        }
      };

      const anchor = criteria.anchorWord.trim();
      const domainIsExpansionOnly = Boolean(anchor && criteria.includeSameDomain);

      const params: Record<string, string> = {};
      if (criteria.query) params.query = criteria.query;
      if (criteria.tier) params.tier = criteria.tier;
      if (criteria.domain && !domainIsExpansionOnly) params.domain = criteria.domain;
      if (criteria.category) params.category = criteria.category;

      const hasBaseFilters =
        Boolean(criteria.query) ||
        Boolean(criteria.tier) ||
        Boolean(criteria.category) ||
        Boolean(params.domain);
      if (hasBaseFilters || !anchor) {
        addRows(await api.searchWords(params));
      }

      if (anchor) {
        try {
          addRows([await api.getWord(anchor)]);
        } catch {
          // Anchor may exist only in dict files, not yet in the converted index.
        }

        const expandRelated =
          criteria.includeSynonyms || criteria.includeAntonyms || criteria.includeSameDomain;
        if (!expandRelated) {
          return Array.from(rowMap.values());
        }

        const anchorWordInfo = await api.getWordEdit(anchor);
        const relatedTokens = new Set<string>();
        if (criteria.includeSynonyms) {
          anchorWordInfo.synonyms.forEach((item) => relatedTokens.add(item.trim().toLowerCase()));
        }
        if (criteria.includeAntonyms) {
          anchorWordInfo.antonyms.forEach((item) => relatedTokens.add(item.trim().toLowerCase()));
        }
        for (const token of relatedTokens) {
          if (!token) continue;
          try {
            const related = await api.getWord(token);
            addRows([related]);
          } catch {
            // Ignore related tokens that are not in the index.
          }
        }

        if (criteria.includeSameDomain) {
          const sameDomain = criteria.domain.trim() || anchorWordInfo.domain.trim();
          if (sameDomain) {
            addRows(await api.searchWords({ domain: sameDomain }));
          }
        }
      }
      return Array.from(rowMap.values());
    }
    if (criteria.mode === "categories") {
      return await api.searchCategories(criteria.query);
    }
    return await api.wordPairs(criteria.pairWord);
  }, []);

  const fetchRows = useCallback(async () => {
    setRows(await fetchRowsForState(state));
  }, [fetchRowsForState, state]);

  useEffect(() => {
    onRegisterRefresh(() => fetchRows);
  }, [onRegisterRefresh, fetchRows]);

  const search = () => onSearch(fetchRows);

  const applyWordCriteria = (
    token: string,
    patch: Partial<SearchState>,
    confirmationMessage: (target: string) => string,
  ) =>
    onSearch(async () => {
      const nextState: SearchState = {
        ...state,
        mode: "words",
        anchorWord: token,
        ...patch,
      };
      onStateChange(nextState);
      setRows(await fetchRowsForState(nextState));
      onMessage(confirmationMessage(token));
    });

  const searchWordDomain = (token: string) =>
    onSearch(async () => {
      const word = await api.getWordEdit(token);
      if (!word.domain.trim()) {
        onMessage(`Word ${word.word} has no domain value.`);
        return;
      }
      const nextState: SearchState = {
        ...state,
        mode: "words",
        anchorWord: token,
        includeSynonyms: false,
        includeAntonyms: false,
        includeSameDomain: true,
      };
      onStateChange(nextState);
      setRows(await fetchRowsForState(nextState));
      onMessage(`Loaded words in domain ${word.domain}.`);
    });

  const wordColumns: DataTableColumn[] | undefined =
    mode === "words"
      ? [
          ...Object.keys(rows[0] ?? {})
            .filter((key) => !HIDDEN_WORD_FIELDS.has(key))
            .map((key) => ({ key, header: key })),
          {
            key: "__actions",
            header: "Actions",
            render: (row) => {
              const token = String(row.word ?? "").trim();
              return (
                <div className="form-row">
                  <button disabled={!token} onClick={() => token && onOpenEditor("word", token)}>
                    Edit
                  </button>
                  <details>
                    <summary>More</summary>
                    <div className="form-row">
                      <button
                        disabled={!token}
                        onClick={() =>
                          token &&
                          applyWordCriteria(
                            token,
                            {
                              includeSynonyms: true,
                              includeAntonyms: false,
                              includeSameDomain: false,
                              domain: "",
                            },
                            (target) => `Updated search criteria to include synonyms for ${target}.`,
                          )
                        }
                      >
                        Show synonyms
                      </button>
                      <button
                        disabled={!token}
                        onClick={() =>
                          token &&
                          applyWordCriteria(
                            token,
                            {
                              includeSynonyms: false,
                              includeAntonyms: true,
                              includeSameDomain: false,
                              domain: "",
                            },
                            (target) => `Updated search criteria to include antonyms for ${target}.`,
                          )
                        }
                      >
                        Show antonyms
                      </button>
                      <button disabled={!token} onClick={() => token && searchWordDomain(token)}>
                        Search by this domain
                      </button>
                    </div>
                  </details>
                </div>
              );
            },
          },
        ]
      : undefined;

  const categoryColumns: DataTableColumn[] | undefined =
    mode === "categories"
      ? [
          ...Object.keys(rows[0] ?? {}).map((key) => ({ key, header: key })),
          {
            key: "__actions",
            header: "Actions",
            render: (row) => {
              const name = String(row.category_name ?? "").trim();
              return (
                <button disabled={!name} onClick={() => name && onOpenEditor("category", name)}>
                  Edit
                </button>
              );
            },
          },
        ]
      : undefined;

  const columns = mode === "words" ? wordColumns : mode === "categories" ? categoryColumns : undefined;

  const normalizedRows = rows.map((row) => {
    const next = { ...row };
    delete next.__actions;
    return next;
  });

  return (
    <section className="panel">
      <h2>Search ontology</h2>
      <div className="form-row">
        <label>
          Mode
          <select value={mode} onChange={(e) => setMode(e.target.value as SearchMode)}>
            <option value="words">Words</option>
            <option value="categories">Categories</option>
            <option value="pairs">Word pairs</option>
          </select>
        </label>
        {mode === "words" && (
          <label>
            Anchor word
            <input value={anchorWord} onChange={(e) => setAnchorWord(e.target.value)} placeholder="e.g. attack" />
          </label>
        )}
        {mode !== "pairs" && (
          <label>
            Query
            <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="substring" />
          </label>
        )}
        {mode === "words" && (
          <>
            <label>
              Tier
              <select value={tier} onChange={(e) => setTier(e.target.value)}>
                <option value="">any</option>
                <option value="very_high">very_high</option>
                <option value="high">high</option>
                <option value="riskable">riskable</option>
                <option value="low">low</option>
                <option value="very_low">very_low</option>
              </select>
            </label>
            <label>
              Domain
                <input value={domain} onChange={(e) => setDomain(e.target.value)} />
            </label>
            <label>
              Category
                <input value={category} onChange={(e) => setCategory(e.target.value)} />
            </label>
            <label>
              <span>Include synonyms</span>
              <input
                type="checkbox"
                checked={includeSynonyms}
                onChange={(e) => setIncludeSynonyms(e.target.checked)}
              />
            </label>
            <label>
              <span>Include antonyms</span>
              <input
                type="checkbox"
                checked={includeAntonyms}
                onChange={(e) => setIncludeAntonyms(e.target.checked)}
              />
            </label>
            <label>
              <span>Include same domain</span>
              <input
                type="checkbox"
                checked={includeSameDomain}
                onChange={(e) => setIncludeSameDomain(e.target.checked)}
              />
            </label>
          </>
        )}
        {mode === "pairs" && (
          <label>
            Word
            <input value={pairWord} onChange={(e) => setPairWord(e.target.value)} placeholder="e.g. carbon" />
          </label>
        )}
        <button className="primary" disabled={loading} onClick={search}>
          Search
        </button>
      </div>
      <DataTable rows={normalizedRows} columns={columns} />
    </section>
  );
}

function TreePanel({
  loading,
  onSearch,
  onOpenEditor,
  onMessage,
  onRegisterRefresh,
}: {
  loading: boolean;
  onSearch: (fn: () => Promise<void>) => void;
  onOpenEditor: (kind: "word" | "category", key: string) => void;
  onMessage: (m: string) => void;
  onRegisterRefresh: Dispatch<SetStateAction<(() => Promise<void>) | null>>;
}) {
  const [root, setRoot] = useState("lexicon");
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const loadRows = useCallback(async () => {
    setRows(await api.categoryTree(root));
  }, [root]);

  useEffect(() => {
    onRegisterRefresh(() => loadRows);
  }, [onRegisterRefresh, loadRows]);

  const treeColumns: DataTableColumn[] = [
    ...Object.keys(rows[0] ?? {}).map((key) => ({ key, header: key })),
    {
      key: "__actions",
      header: "Actions",
      render: (row) => {
        const name = String(row.category_name ?? "").trim();
        return (
          <div className="form-row">
            <button disabled={!name} onClick={() => name && onOpenEditor("category", name)}>
              Edit
            </button>
            <details>
              <summary>More</summary>
              <div className="form-row">
                <button
                  disabled={!name}
                  onClick={() =>
                    name &&
                    onSearch(async () => {
                      const words = await api.wordsInCategory(name, true);
                      setRows(words);
                      onMessage(`Loaded direct words in ${name}.`);
                    })
                  }
                >
                  Search words in this category
                </button>
                <button disabled={!name} onClick={() => name && setRoot(name)}>
                  Set as tree root
                </button>
              </div>
            </details>
          </div>
        );
      },
    },
  ];

  const normalizedRows = rows.map((row) => {
    const next = { ...row };
    delete next.__actions;
    return next;
  });

  return (
    <section className="panel">
      <h2>Category tree</h2>
      <div className="form-row">
        <label>
          Root
          <input value={root} onChange={(e) => setRoot(e.target.value)} />
        </label>
        <button
          className="primary"
          disabled={loading}
          onClick={() => onSearch(loadRows)}
        >
          Load tree
        </button>
      </div>
      <DataTable rows={normalizedRows} columns={treeColumns} />
    </section>
  );
}

const KEYWORD_PURPOSES = [
  "word_section_starter",
  "meaning_section_starter",
  "synonym_section_starter",
  "antonym_section_starter",
  "category_tags_starter",
  "domain_section_starter",
  "pos_section_starter",
  "register_section_starter",
  "risk_level_section_starter",
  "infer_category_relation",
];

const emptyKeywordForm = (): Omit<KeywordSeed, "id"> => ({
  keyword: "",
  purpose_of_keyword: KEYWORD_PURPOSES[0],
  is_regex: true,
  ontology_relation: "",
});

function KeywordsPanel({
  loading,
  onAction,
  onMessage,
}: {
  loading: boolean;
  onAction: (fn: () => Promise<void>) => void;
  onMessage: (m: string) => void;
}) {
  const [seeds, setSeeds] = useState<KeywordSeed[]>([]);
  const [filter, setFilter] = useState("");
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(emptyKeywordForm());

  const load = useCallback(async () => {
    setSeeds(await api.keywordSeeds());
  }, []);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const filtered = seeds.filter((seed) => {
    const haystack = `${seed.id} ${seed.keyword} ${seed.purpose_of_keyword} ${seed.ontology_relation}`.toLowerCase();
    return haystack.includes(filter.toLowerCase());
  });

  const selectSeed = (seed: KeywordSeed) => {
    setCreating(false);
    setSelectedId(seed.id);
    setForm({
      keyword: seed.keyword,
      purpose_of_keyword: seed.purpose_of_keyword,
      is_regex: seed.is_regex,
      ontology_relation: seed.ontology_relation,
    });
  };

  const startCreate = () => {
    setCreating(true);
    setSelectedId(null);
    setForm(emptyKeywordForm());
  };

  const save = () =>
    onAction(async () => {
      if (creating) {
        await api.createKeywordSeed(form);
        onMessage("Keyword seed created.");
      } else if (selectedId !== null) {
        await api.updateKeywordSeed(selectedId, form);
        onMessage(`Keyword seed ${selectedId} updated.`);
      }
      await load();
      setCreating(false);
    });

  const remove = () =>
    onAction(async () => {
      if (selectedId === null) return;
      if (!window.confirm(`Delete keyword seed ${selectedId}?`)) return;
      await api.deleteKeywordSeed(selectedId);
      onMessage(`Keyword seed ${selectedId} deleted.`);
      setSelectedId(null);
      setForm(emptyKeywordForm());
      await load();
    });

  return (
    <section className="panel">
      <h2>Keyword seeds</h2>
      <p>
        Manage parser regex rules in <code>dictgraph/keywords_seed.json</code>. Re-run convert after
        changes to apply them.
      </p>

      <div className="form-row">
        <label>
          Filter
          <input
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
            placeholder="id, keyword, purpose…"
          />
        </label>
        <button className="primary" disabled={loading} onClick={() => onAction(load)}>
          Refresh
        </button>
        <button disabled={loading} onClick={startCreate}>
          New seed
        </button>
      </div>

      <div className="keywords-layout">
        <div className="keywords-table-wrap">
          <table>
            <thead>
              <tr>
                <th>ID</th>
                <th>Purpose</th>
                <th>Keyword</th>
                <th>Regex</th>
                <th>Ontology</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((seed) => (
                <tr
                  key={seed.id}
                  className={selectedId === seed.id && !creating ? "selected-row" : ""}
                  onClick={() => selectSeed(seed)}
                >
                  <td>{seed.id}</td>
                  <td>{seed.purpose_of_keyword}</td>
                  <td className="mono-cell">{seed.keyword}</td>
                  <td>{seed.is_regex ? "yes" : "no"}</td>
                  <td>{seed.ontology_relation || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {filtered.length === 0 && <p>No keyword seeds match the filter.</p>}
        </div>

        <div className="keywords-editor">
          <h3>{creating ? "Create keyword seed" : selectedId !== null ? `Edit #${selectedId}` : "Select a row"}</h3>
          <div className="form-row">
            <label className="wide">
              Keyword
              <textarea
                value={form.keyword}
                onChange={(e) => setForm({ ...form, keyword: e.target.value })}
                placeholder="(?i)^meaning\s*:"
              />
            </label>
          </div>
          <div className="form-row">
            <label>
              Purpose
              <select
                value={form.purpose_of_keyword}
                onChange={(e) => setForm({ ...form, purpose_of_keyword: e.target.value })}
              >
                {KEYWORD_PURPOSES.map((purpose) => (
                  <option key={purpose} value={purpose}>
                    {purpose}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Ontology relation
              <input
                value={form.ontology_relation}
                onChange={(e) => setForm({ ...form, ontology_relation: e.target.value })}
                placeholder="is_a_type_of"
              />
            </label>
            <label>
              <span>Regex</span>
              <input
                type="checkbox"
                checked={form.is_regex}
                onChange={(e) => setForm({ ...form, is_regex: e.target.checked })}
              />
            </label>
          </div>
          <div className="form-row">
            <button
              className="primary"
              disabled={loading || (!creating && selectedId === null) || !form.keyword.trim()}
              onClick={save}
            >
              {creating ? "Create" : "Save changes"}
            </button>
            {!creating && selectedId !== null && (
              <button className="danger" disabled={loading} onClick={remove}>
                Delete
              </button>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function SafetyPanel({
  loading,
  onAction,
  onMessage,
  refreshHealth,
}: {
  loading: boolean;
  onAction: (fn: () => Promise<void>) => void;
  onMessage: (m: string) => void;
  refreshHealth: () => void;
}) {
  const [audit, setAudit] = useState<Record<string, unknown>[]>([]);
  const [entityType, setEntityType] = useState("word");
  const [entityKey, setEntityKey] = useState("");
  const [score, setScore] = useState("0.5");
  const [reason, setReason] = useState("");
  const [actor, setActor] = useState("reviewer");

  const load = useCallback(async () => {
    setAudit(await api.audit(30));
    refreshHealth();
  }, [refreshHealth]);

  useEffect(() => {
    load().catch(() => {});
  }, [load]);

  const submit = () =>
    onAction(async () => {
      await api.applyDirect({
        entity_type: entityType,
        entity_key: entityKey,
        score: parseFloat(score),
        reason,
        actor,
      });
      onMessage("Score applied and CSVs regenerated.");
      await load();
    });

  return (
    <section className="panel">
      <h2>Safety scores — direct apply</h2>

      <h3>Apply score</h3>
      <div className="form-row">
        <label>
          Type
          <select value={entityType} onChange={(e) => setEntityType(e.target.value)}>
            <option value="word">word</option>
            <option value="category">category</option>
            <option value="word_pair">word_pair (a,b)</option>
          </select>
        </label>
        <label>
          Key
          <input
            value={entityKey}
            onChange={(e) => setEntityKey(e.target.value)}
            placeholder={entityType === "word_pair" ? "carbon,monoxide" : "attack"}
          />
        </label>
        <label>
          Score (0–1)
          <input type="number" min={0} max={1} step={0.01} value={score} onChange={(e) => setScore(e.target.value)} />
        </label>
        <label>
          Reason
          <textarea value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <label>
          Actor
          <input value={actor} onChange={(e) => setActor(e.target.value)} />
        </label>
        <button className="primary" disabled={loading || !entityKey || !reason} onClick={submit}>
          Apply now
        </button>
      </div>

      <h3>Audit log</h3>
      <DataTable rows={audit} />
    </section>
  );
}
