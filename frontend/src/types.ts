export interface HealthResponse {
  status: 'ok'
  version: string
}

export interface StoreStatus {
  documents: number
  chunks: number
  last_sync_at: string | null
  last_sync_status: string | null
}

export interface OperationalMetrics {
  documents: number
  chunks: number
  sync_runs_running: number
  sync_runs_succeeded: number
  sync_runs_failed: number
  new_documents_total: number
  changed_documents_total: number
  metadata_changed_documents_total: number
  deleted_documents_total: number
  unchanged_documents_total: number
  embedded_chunks_total: number
  deleted_chunks_total: number
  scanned_documents_total: number
  scanned_bytes_total: number
  embedding_batches_total: number
  embedding_duration_ms_total: number
  last_sync_status: string | null
  last_sync_at: string | null
  last_sync_duration_ms: number | null
}

export interface SyncRun {
  run_id: string
  source: string
  status: string
  new_documents: number
  changed_documents: number
  metadata_changed_documents: number
  deleted_documents: number
  unchanged_documents: number
  embedded_chunks: number
  deleted_chunks: number
  scanned_documents: number
  scanned_bytes: number
  embedding_batches: number
  embedding_duration_ms: number
  started_at: string
  finished_at: string
  duration_ms: number
  error: string | null
}

export interface RunsResponse {
  limit: number
  count: number
  runs: SyncRun[]
}

export interface SyncResult {
  run_id: string
  status: string
  new_documents: number
  changed_documents: number
  deleted_documents: number
  unchanged_documents: number
  embedded_chunks: number
  deleted_chunks: number
  started_at: string
  finished_at: string
  metadata_changed_documents: number
  scanned_documents: number
  scanned_bytes: number
  embedding_batches: number
  embedding_duration_ms: number
}

export interface SearchResult {
  document_path: string
  chunk_index: number
  content: string
  metadata: Record<string, unknown>
  embedding_model: string
  score: number
}

export interface SearchResponse {
  query: string
  metadata_filter: Record<string, unknown> | null
  embedding_model: string
  count: number
  results: SearchResult[]
}

export interface DashboardData {
  health: HealthResponse
  status: StoreStatus
  metrics: OperationalMetrics
  runs: RunsResponse
}
