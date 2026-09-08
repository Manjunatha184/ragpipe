import type { ReactNode } from 'react'

import {
  formatDate,
  formatDuration,
  formatNumber,
  shortSource,
} from './formatters'
import type { OperationalMetrics, SyncRun } from './types'

export type IconName =
  | 'activity'
  | 'database'
  | 'documents'
  | 'refresh'
  | 'search'
  | 'server'
  | 'spark'
  | 'time'

interface IconProps {
  name: IconName
  size?: number
}

export function Icon({ name, size = 20 }: IconProps) {
  const paths: Record<IconName, ReactNode> = {
    activity: <path d="M3 12h4l2-7 4 14 2-7h6" />,
    database: (
      <>
        <ellipse cx="12" cy="5" rx="8" ry="3" />
        <path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" />
      </>
    ),
    documents: (
      <>
        <path d="M7 3h7l4 4v14H7z" />
        <path d="M14 3v5h5M10 13h5M10 17h5" />
      </>
    ),
    refresh: <path d="M20 7v5h-5M4 17v-5h5M6.1 8a7 7 0 0 1 11.4-2.2L20 8M4 16l2.5 2.2A7 7 0 0 0 17.9 16" />,
    search: (
      <>
        <circle cx="11" cy="11" r="7" />
        <path d="m20 20-4-4" />
      </>
    ),
    server: (
      <>
        <rect x="3" y="4" width="18" height="6" rx="2" />
        <rect x="3" y="14" width="18" height="6" rx="2" />
        <path d="M7 7h.01M7 17h.01" />
      </>
    ),
    spark: <path d="m12 2 1.7 6.3L20 10l-6.3 1.7L12 18l-1.7-6.3L4 10l6.3-1.7zM19 16l.7 2.3L22 19l-2.3.7L19 22l-.7-2.3L16 19l2.3-.7z" />,
    time: (
      <>
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v5l3 2" />
      </>
    ),
  }

  return (
    <svg
      aria-hidden="true"
      className="icon"
      fill="none"
      height={size}
      viewBox="0 0 24 24"
      width={size}
    >
      <g stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8">
        {paths[name]}
      </g>
    </svg>
  )
}

interface MetricCardProps {
  icon: IconName
  label: string
  value: string
  detail: string
  tone?: 'blue' | 'green' | 'violet' | 'amber'
}

export function MetricCard({ icon, label, value, detail, tone = 'blue' }: MetricCardProps) {
  return (
    <article className={`metric-card metric-card--${tone}`}>
      <div className="metric-card__top">
        <span className="metric-card__icon"><Icon name={icon} /></span>
        <span className="metric-card__label">{label}</span>
      </div>
      <strong>{value}</strong>
      <span className="metric-card__detail">{detail}</span>
    </article>
  )
}

export function StatusPill({ status }: { status: string | null }) {
  const normalized = status?.toLowerCase() ?? 'unknown'
  return (
    <span className={`status-pill status-pill--${normalized}`}>
      <span className="status-pill__dot" />
      {status ?? 'Unknown'}
    </span>
  )
}

export function ChangeDistribution({ metrics }: { metrics: OperationalMetrics }) {
  const values = [
    { label: 'New', value: metrics.new_documents_total, color: 'var(--green)' },
    { label: 'Content', value: metrics.changed_documents_total, color: 'var(--blue)' },
    { label: 'Metadata', value: metrics.metadata_changed_documents_total, color: 'var(--violet)' },
    { label: 'Deleted', value: metrics.deleted_documents_total, color: 'var(--red)' },
    { label: 'Unchanged', value: metrics.unchanged_documents_total, color: 'var(--slate)' },
  ]
  const maximum = Math.max(...values.map((item) => item.value), 1)

  return (
    <div className="change-list">
      {values.map((item) => (
        <div className="change-row" key={item.label}>
          <div className="change-row__label">
            <span>{item.label}</span>
            <strong>{formatNumber(item.value)}</strong>
          </div>
          <div className="change-row__track">
            <span
              style={{
                background: item.color,
                width: `${Math.max((item.value / maximum) * 100, item.value > 0 ? 3 : 0)}%`,
              }}
            />
          </div>
        </div>
      ))}
    </div>
  )
}

export function DurationChart({ runs }: { runs: SyncRun[] }) {
  const chartRuns = [...runs].slice(0, 8).reverse()
  const maximum = Math.max(...chartRuns.map((run) => run.duration_ms), 1)

  if (chartRuns.length === 0) {
    return <EmptyState compact message="Run a synchronization to see duration history." />
  }

  return (
    <div className="duration-chart" aria-label="Recent synchronization duration chart">
      {chartRuns.map((run) => (
        <div className="duration-bar" key={run.run_id} title={formatDuration(run.duration_ms)}>
          <span
            className={run.status === 'succeeded' ? 'duration-bar__fill' : 'duration-bar__fill duration-bar__fill--failed'}
            style={{ height: `${Math.max((run.duration_ms / maximum) * 100, 5)}%` }}
          />
          <small>{new Date(run.finished_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</small>
        </div>
      ))}
    </div>
  )
}

export function RunsTable({ runs, limit }: { runs: SyncRun[]; limit?: number }) {
  const visibleRuns = limit ? runs.slice(0, limit) : runs

  if (visibleRuns.length === 0) {
    return <EmptyState message="No synchronization runs have been recorded." />
  }

  return (
    <div className="table-shell">
      <table>
        <thead>
          <tr>
            <th>Status</th>
            <th>Source</th>
            <th>Scanned</th>
            <th>Changes</th>
            <th>Embedded</th>
            <th>Duration</th>
            <th>Finished</th>
          </tr>
        </thead>
        <tbody>
          {visibleRuns.map((run) => {
            const changes =
              run.new_documents +
              run.changed_documents +
              run.metadata_changed_documents +
              run.deleted_documents
            return (
              <tr key={run.run_id}>
                <td><StatusPill status={run.status} /></td>
                <td>
                  <span className="source-cell" title={run.source}>{shortSource(run.source)}</span>
                  <small>{run.run_id.slice(0, 8)}</small>
                </td>
                <td>{formatNumber(run.scanned_documents)}</td>
                <td>{formatNumber(changes)}</td>
                <td>{formatNumber(run.embedded_chunks)}</td>
                <td>{formatDuration(run.duration_ms)}</td>
                <td>{formatDate(run.finished_at)}</td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

export function EmptyState({ message, compact = false }: { message: string; compact?: boolean }) {
  return (
    <div className={compact ? 'empty-state empty-state--compact' : 'empty-state'}>
      <Icon name="documents" size={24} />
      <span>{message}</span>
    </div>
  )
}
