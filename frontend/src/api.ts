import type {
  DashboardData,
  HealthResponse,
  OperationalMetrics,
  RunsResponse,
  SearchResponse,
  StoreStatus,
  SyncResult,
} from './types'

const configuredBaseUrl = import.meta.env.VITE_API_BASE_URL as string | undefined
const API_BASE_URL = configuredBaseUrl?.replace(/\/$/, '') ?? ''
export const API_DOCS_URL = `${API_BASE_URL}/docs`

interface ErrorPayload {
  error?: string
  detail?: string | Array<{ msg?: string }>
}

export class ApiError extends Error {
  readonly statusCode: number

  constructor(message: string, statusCode: number) {
    super(message)
    this.name = 'ApiError'
    this.statusCode = statusCode
  }
}

function validationMessage(detail: ErrorPayload['detail']): string | null {
  if (typeof detail === 'string') return detail
  if (!Array.isArray(detail)) return null

  const messages = detail
    .map((item) => item.msg)
    .filter((message): message is string => Boolean(message))

  return messages.length > 0 ? messages.join(' ') : null
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const headers = new Headers(options?.headers)
  headers.set('Accept', 'application/json')

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...options,
    headers,
  })

  const payload = (await response.json().catch(() => null)) as ErrorPayload | T | null

  if (!response.ok) {
    const errorPayload = payload as ErrorPayload | null
    const message =
      errorPayload?.error ??
      validationMessage(errorPayload?.detail) ??
      `Request failed with status ${response.status}.`
    throw new ApiError(message, response.status)
  }

  return payload as T
}

export async function getDashboardData(): Promise<DashboardData> {
  const [health, status, metrics, runs] = await Promise.all([
    request<HealthResponse>('/api/v1/health'),
    request<StoreStatus>('/api/v1/status'),
    request<OperationalMetrics>('/api/v1/metrics'),
    request<RunsResponse>('/api/v1/runs?limit=50'),
  ])

  return { health, status, metrics, runs }
}

export function startSync(source: string): Promise<SyncResult> {
  return request<SyncResult>('/api/v1/sync', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ source }),
  })
}

export function semanticSearch(
  query: string,
  limit: number,
  metadataFilter: Record<string, unknown> | null,
): Promise<SearchResponse> {
  return request<SearchResponse>('/api/v1/search', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      query,
      limit,
      metadata_filter: metadataFilter,
    }),
  })
}
