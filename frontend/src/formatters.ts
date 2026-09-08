export function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value)
}

export function formatBytes(value: number): string {
  if (value === 0) return '0 B'

  const units = ['B', 'KB', 'MB', 'GB']
  const unitIndex = Math.min(
    Math.floor(Math.log(value) / Math.log(1024)),
    units.length - 1,
  )

  return `${(value / 1024 ** unitIndex).toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

export function formatDuration(value: number | null): string {
  if (value === null) return '—'
  if (value < 1000) return `${value.toFixed(value < 10 ? 2 : 0)} ms`
  return `${(value / 1000).toFixed(2)} s`
}

export function formatDate(value: string | null): string {
  if (!value) return 'No sync recorded'
  return new Intl.DateTimeFormat('en-IN', {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(value))
}

export function shortSource(source: string): string {
  if (source.startsWith('s3://')) return source
  const parts = source.split('/').filter(Boolean)
  return parts.slice(-2).join('/') || source
}
