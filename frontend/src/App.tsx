import { type FormEvent, useEffect, useState } from 'react'

import { API_DOCS_URL, ApiError, getDashboardData, semanticSearch, startSync } from './api'
import {
  ChangeDistribution,
  DurationChart,
  EmptyState,
  Icon,
  MetricCard,
  RunsTable,
  StatusPill,
  type IconName,
} from './components'
import { formatBytes, formatDate, formatDuration, formatNumber } from './formatters'
import type { DashboardData, SearchResponse, SyncResult } from './types'
import './App.css'

type View = 'overview' | 'sync' | 'search' | 'runs'
type SourceType = 'local' | 's3'

const navigation: Array<{ id: View; label: string; icon: IconName }> = [
  { id: 'overview', label: 'Overview', icon: 'activity' },
  { id: 'sync', label: 'Synchronize', icon: 'refresh' },
  { id: 'search', label: 'Search', icon: 'search' },
  { id: 'runs', label: 'Run history', icon: 'time' },
]

function errorMessage(error: unknown): string {
  if (error instanceof ApiError || error instanceof Error) return error.message
  return 'An unexpected error occurred.'
}

function App() {
  const [activeView, setActiveView] = useState<View>('overview')
  const [dashboard, setDashboard] = useState<DashboardData | null>(null)
  const [dashboardError, setDashboardError] = useState<string | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [lastRefreshed, setLastRefreshed] = useState<Date | null>(null)

  const [sourceType, setSourceType] = useState<SourceType>('local')
  const [source, setSource] = useState('sample_docs')
  const [isSyncing, setIsSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState<SyncResult | null>(null)
  const [syncError, setSyncError] = useState<string | null>(null)

  const [query, setQuery] = useState('What does this documentation explain?')
  const [searchLimit, setSearchLimit] = useState(5)
  const [metadataText, setMetadataText] = useState('')
  const [isSearching, setIsSearching] = useState(false)
  const [searchResponse, setSearchResponse] = useState<SearchResponse | null>(null)
  const [searchError, setSearchError] = useState<string | null>(null)

  async function refreshDashboard(showLoader = true) {
    if (showLoader) setIsLoading(true)
    try {
      const data = await getDashboardData()
      setDashboard(data)
      setDashboardError(null)
      setLastRefreshed(new Date())
    } catch (error) {
      setDashboardError(errorMessage(error))
    } finally {
      if (showLoader) setIsLoading(false)
    }
  }

  useEffect(() => {
    let active = true
    getDashboardData()
      .then((data) => {
        if (!active) return
        setDashboard(data)
        setDashboardError(null)
        setLastRefreshed(new Date())
      })
      .catch((error: unknown) => {
        if (active) setDashboardError(errorMessage(error))
      })
      .finally(() => {
        if (active) setIsLoading(false)
      })

    return () => {
      active = false
    }
  }, [])

  function changeSourceType(type: SourceType) {
    setSourceType(type)
    setSource(type === 'local' ? 'sample_docs' : 's3://bucket/prefix')
    setSyncError(null)
  }

  async function handleSync(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSyncing(true)
    setSyncError(null)
    setSyncResult(null)

    try {
      const result = await startSync(source.trim())
      setSyncResult(result)
      await refreshDashboard(false)
    } catch (error) {
      setSyncError(errorMessage(error))
    } finally {
      setIsSyncing(false)
    }
  }

  async function handleSearch(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setIsSearching(true)
    setSearchError(null)
    setSearchResponse(null)

    try {
      let metadataFilter: Record<string, unknown> | null = null
      if (metadataText.trim()) {
        const parsed: unknown = JSON.parse(metadataText)
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('Metadata filter must be a JSON object.')
        }
        metadataFilter = parsed as Record<string, unknown>
      }

      setSearchResponse(await semanticSearch(query.trim(), searchLimit, metadataFilter))
    } catch (error) {
      setSearchError(error instanceof SyntaxError ? 'Metadata filter is not valid JSON.' : errorMessage(error))
    } finally {
      setIsSearching(false)
    }
  }

  const metrics = dashboard?.metrics
  const runs = dashboard?.runs.runs ?? []
  const totalCompletedRuns = metrics
    ? metrics.sync_runs_succeeded + metrics.sync_runs_failed
    : 0
  const successRate = metrics && totalCompletedRuns > 0
    ? (metrics.sync_runs_succeeded / totalCompletedRuns) * 100
    : 0

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brand__mark"><span /></span>
          <div><strong>ragpipe</strong><small>Vector operations</small></div>
        </div>

        <nav aria-label="Primary navigation">
          <span className="sidebar__label">Workspace</span>
          {navigation.map((item) => (
            <button
              className={activeView === item.id ? 'nav-item nav-item--active' : 'nav-item'}
              key={item.id}
              onClick={() => setActiveView(item.id)}
              type="button"
            >
              <Icon name={item.icon} />
              <span>{item.label}</span>
            </button>
          ))}
        </nav>

        <div className="sidebar__footer">
          <div className="environment-card">
            <span className={dashboardError ? 'connection-dot connection-dot--offline' : 'connection-dot'} />
            <div>
              <strong>{dashboardError ? 'API unavailable' : 'API connected'}</strong>
              <small>{dashboard?.health.version ? `Version ${dashboard.health.version}` : 'Checking service'}</small>
            </div>
          </div>
          <a href={API_DOCS_URL} rel="noreferrer" target="_blank">Open API documentation <span>↗</span></a>
        </div>
      </aside>

      <main>
        <header className="topbar">
          <div>
            <p>Operations console</p>
            <h1>{navigation.find((item) => item.id === activeView)?.label}</h1>
          </div>
          <div className="topbar__actions">
            <span className="last-updated">
              {lastRefreshed ? `Updated ${lastRefreshed.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}` : 'Not updated'}
            </span>
            <button className="icon-button" disabled={isLoading} onClick={() => void refreshDashboard()} title="Refresh data" type="button">
              <Icon name="refresh" />
            </button>
            <div className="avatar" title="Local operator">M</div>
          </div>
        </header>

        <div className="content">
          {dashboardError && (
            <div className="alert alert--error">
              <strong>Could not reach the Ragpipe API.</strong>
              <span>{dashboardError} Confirm that FastAPI is running on port 8000.</span>
            </div>
          )}

          {activeView === 'overview' && (
            <section className="view">
              <div className="view-heading">
                <div><h2>Corpus overview</h2><p>Live state of your synchronized knowledge base.</p></div>
                <StatusPill status={dashboard?.status.last_sync_status ?? null} />
              </div>

              <div className="metric-grid">
                <MetricCard icon="documents" label="Documents" value={formatNumber(metrics?.documents ?? 0)} detail={`${formatNumber(metrics?.scanned_documents_total ?? 0)} scanned across all runs`} tone="blue" />
                <MetricCard icon="database" label="Stored chunks" value={formatNumber(metrics?.chunks ?? 0)} detail={`${formatNumber(metrics?.embedded_chunks_total ?? 0)} embeddings committed`} tone="violet" />
                <MetricCard icon="activity" label="Successful runs" value={formatNumber(metrics?.sync_runs_succeeded ?? 0)} detail={`${successRate.toFixed(1)}% completion rate`} tone="green" />
                <MetricCard icon="time" label="Last duration" value={formatDuration(metrics?.last_sync_duration_ms ?? null)} detail={formatDate(metrics?.last_sync_at ?? null)} tone="amber" />
              </div>

              <div className="panel-grid">
                <article className="panel">
                  <div className="panel__header"><div><h3>Document lifecycle</h3><p>All-time change classifications</p></div><Icon name="activity" /></div>
                  {metrics ? <ChangeDistribution metrics={metrics} /> : <EmptyState compact message="Metrics are loading." />}
                </article>
                <article className="panel">
                  <div className="panel__header"><div><h3>Run duration</h3><p>Latest eight synchronization runs</p></div><span className="unit-label">milliseconds</span></div>
                  <DurationChart runs={runs} />
                </article>
              </div>

              <article className="panel panel--table">
                <div className="panel__header">
                  <div><h3>Recent runs</h3><p>Latest synchronization activity and throughput</p></div>
                  <button className="text-button" onClick={() => setActiveView('runs')} type="button">View all</button>
                </div>
                <RunsTable limit={5} runs={runs} />
              </article>
            </section>
          )}

          {activeView === 'sync' && (
            <section className="view view--narrow">
              <div className="view-heading"><div><h2>Synchronize a source</h2><p>Detect changes and update the vector store transactionally.</p></div></div>
              <article className="panel form-panel">
                <div className="source-tabs" role="group" aria-label="Document source type">
                  <button className={sourceType === 'local' ? 'source-tab source-tab--active' : 'source-tab'} onClick={() => changeSourceType('local')} type="button"><Icon name="server" /> Local folder</button>
                  <button className={sourceType === 's3' ? 'source-tab source-tab--active' : 'source-tab'} onClick={() => changeSourceType('s3')} type="button"><Icon name="database" /> Amazon S3</button>
                </div>
                <form onSubmit={handleSync}>
                  <label htmlFor="source">{sourceType === 'local' ? 'Directory inside the allowed API root' : 'S3 bucket and prefix URI'}</label>
                  <div className="input-with-icon"><Icon name={sourceType === 'local' ? 'documents' : 'database'} /><input id="source" onChange={(event) => setSource(event.target.value)} placeholder={sourceType === 'local' ? 'sample_docs' : 's3://company-documents/policies'} required value={source} /></div>
                  <p className="field-help">{sourceType === 'local' ? 'The API rejects paths outside RAGPIPE_API_ALLOWED_LOCAL_ROOT.' : 'The API uses credentials configured in the server environment.'}</p>
                  <button className="primary-button" disabled={isSyncing || !source.trim()} type="submit">{isSyncing ? <><span className="spinner" /> Synchronizing…</> : <><Icon name="refresh" /> Start synchronization</>}</button>
                </form>
              </article>

              {syncError && <div className="alert alert--error"><strong>Synchronization failed</strong><span>{syncError}</span></div>}
              {syncResult && (
                <article className="panel result-panel">
                  <div className="result-panel__heading"><div className="success-mark">✓</div><div><h3>Synchronization completed</h3><p>Run {syncResult.run_id}</p></div><StatusPill status={syncResult.status} /></div>
                  <div className="result-grid">
                    <div><span>Scanned</span><strong>{formatNumber(syncResult.scanned_documents)}</strong></div>
                    <div><span>New</span><strong>{formatNumber(syncResult.new_documents)}</strong></div>
                    <div><span>Content changed</span><strong>{formatNumber(syncResult.changed_documents)}</strong></div>
                    <div><span>Metadata changed</span><strong>{formatNumber(syncResult.metadata_changed_documents)}</strong></div>
                    <div><span>Deleted documents</span><strong>{formatNumber(syncResult.deleted_documents)}</strong></div>
                    <div><span>Unchanged</span><strong>{formatNumber(syncResult.unchanged_documents)}</strong></div>
                    <div><span>Embedded chunks</span><strong>{formatNumber(syncResult.embedded_chunks)}</strong></div>
                    <div><span>Deleted chunks</span><strong>{formatNumber(syncResult.deleted_chunks)}</strong></div>
                    <div><span>Embedding time</span><strong>{formatDuration(syncResult.embedding_duration_ms)}</strong></div>
                  </div>
                </article>
              )}
            </section>
          )}

          {activeView === 'search' && (
            <section className="view view--narrow">
              <div className="view-heading"><div><h2>Semantic search</h2><p>Search document meaning using pgvector cosine similarity.</p></div></div>
              <article className="panel form-panel search-form">
                <form onSubmit={handleSearch}>
                  <label htmlFor="query">Natural-language query</label>
                  <textarea id="query" onChange={(event) => setQuery(event.target.value)} placeholder="Ask a question about the synchronized documents" required rows={3} value={query} />
                  <div className="form-row">
                    <div><label htmlFor="limit">Result limit</label><select id="limit" onChange={(event) => setSearchLimit(Number(event.target.value))} value={searchLimit}><option value="3">3 results</option><option value="5">5 results</option><option value="10">10 results</option><option value="20">20 results</option></select></div>
                    <div className="form-row__wide"><label htmlFor="metadata">Metadata filter <span>optional JSON</span></label><input id="metadata" onChange={(event) => setMetadataText(event.target.value)} placeholder='{"department":"engineering"}' value={metadataText} /></div>
                  </div>
                  <button className="primary-button" disabled={isSearching || !query.trim()} type="submit">{isSearching ? <><span className="spinner" /> Generating query embedding…</> : <><Icon name="spark" /> Search vectors</>}</button>
                </form>
              </article>

              {searchError && <div className="alert alert--error"><strong>Search failed</strong><span>{searchError}</span></div>}
              {searchResponse && (
                <div className="search-results">
                  <div className="search-results__heading"><div><h3>{searchResponse.count} matching {searchResponse.count === 1 ? 'chunk' : 'chunks'}</h3><p>Model: {searchResponse.embedding_model}</p></div></div>
                  {searchResponse.results.length === 0 ? <EmptyState message="No matching chunks were found." /> : searchResponse.results.map((result, index) => (
                    <article className="search-result" key={`${result.document_path}-${result.chunk_index}`}>
                      <div className="search-result__rank">{index + 1}</div>
                      <div className="search-result__body">
                        <div className="search-result__top"><div><strong>{result.document_path}</strong><span>Chunk {result.chunk_index}</span></div><span className="score">Score {result.score.toFixed(4)}</span></div>
                        <p>{result.content}</p>
                        {Object.keys(result.metadata).length > 0 && <div className="metadata-list">{Object.entries(result.metadata).filter(([key]) => key !== 'chunk_index').map(([key, value]) => <span key={key}><small>{key}</small>{Array.isArray(value) ? value.join(', ') : String(value)}</span>)}</div>}
                      </div>
                    </article>
                  ))}
                </div>
              )}
            </section>
          )}

          {activeView === 'runs' && (
            <section className="view">
              <div className="view-heading">
                <div><h2>Synchronization history</h2><p>Inspect source activity, document changes and processing time.</p></div>
                <span className="record-count">{formatNumber(runs.length)} loaded records</span>
              </div>
              <div className="summary-strip">
                <div><span>Successful</span><strong>{formatNumber(metrics?.sync_runs_succeeded ?? 0)}</strong></div>
                <div><span>Failed</span><strong>{formatNumber(metrics?.sync_runs_failed ?? 0)}</strong></div>
                <div><span>Total scanned bytes</span><strong>{formatBytes(metrics?.scanned_bytes_total ?? 0)}</strong></div>
                <div><span>Embedding time</span><strong>{formatDuration(metrics?.embedding_duration_ms_total ?? null)}</strong></div>
              </div>
              <article className="panel panel--table">
                <div className="panel__header">
                  <div><h3>All recent runs</h3><p>Up to 50 records returned by the operational API</p></div>
                  <button className="text-button" disabled={isLoading} onClick={() => void refreshDashboard()} type="button">Refresh history</button>
                </div>
                <RunsTable runs={runs} />
              </article>
            </section>
          )}
        </div>
      </main>
    </div>
  )
}

export default App
