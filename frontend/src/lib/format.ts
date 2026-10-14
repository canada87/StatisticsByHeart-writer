import { it } from '../i18n/it'

export const TZ = 'Europe/Rome'
export const LOCALE = 'it-IT'
const DASH = '—'

const numberFormats = new Map<number, Intl.NumberFormat>()
function nf(digits: number): Intl.NumberFormat {
  let f = numberFormats.get(digits)
  if (!f) {
    f = new Intl.NumberFormat(LOCALE, { maximumFractionDigits: digits, minimumFractionDigits: 0 })
    numberFormats.set(digits, f)
  }
  return f
}

export function fmtNumber(v: number | null | undefined, digits = 0): string {
  return v === null || v === undefined || Number.isNaN(v) ? DASH : nf(digits).format(v)
}

export function fmtPercent(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? DASH : `${v > 0 ? '+' : ''}${nf(digits).format(v)}%`
}

/** 27120 -> "7 h 32 min"; 2700 -> "45 min". */
export function fmtDuration(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return DASH
  const total = Math.max(0, Math.round(seconds / 60))
  const h = Math.floor(total / 60)
  const m = total % 60
  if (h === 0) return `${m} min`
  return m === 0 ? `${h} h` : `${h} h ${m} min`
}

export function fmtDistance(meters: number | null | undefined): string {
  if (meters === null || meters === undefined) return DASH
  return meters >= 1000 ? `${nf(2).format(meters / 1000)} km` : `${nf(0).format(meters)} m`
}

const dateTimeFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: TZ,
  day: '2-digit',
  month: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
})
const timeFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: TZ, hour: '2-digit', minute: '2-digit' })
const dayFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: 'UTC',
  weekday: 'short',
  day: '2-digit',
  month: '2-digit',
})
const dayLongFmt = new Intl.DateTimeFormat(LOCALE, {
  timeZone: 'UTC',
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
})
const dayShortFmt = new Intl.DateTimeFormat(LOCALE, { timeZone: 'UTC', day: '2-digit', month: '2-digit' })

export function fmtDateTime(iso: string | null | undefined): string {
  return iso ? dateTimeFmt.format(new Date(iso)) : DASH
}
export function fmtTime(iso: string | null | undefined): string {
  return iso ? timeFmt.format(new Date(iso)) : DASH
}
/** "2026-10-14" -> "mer 14/10" (a calendar day, no timezone shifting). */
export function fmtDay(day: string | null | undefined): string {
  return day ? dayFmt.format(new Date(`${day}T00:00:00Z`)) : DASH
}
export function fmtDayLong(day: string | null | undefined): string {
  return day ? dayLongFmt.format(new Date(`${day}T00:00:00Z`)) : DASH
}
export function fmtDayShort(day: string): string {
  return dayShortFmt.format(new Date(`${day}T00:00:00Z`))
}

export function timeAgo(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return it['time.never']
  const s = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000))
  if (s < 90) return it['time.now']
  const m = Math.round(s / 60)
  if (m < 60) return `${m} min fa`
  const h = Math.round(m / 60)
  if (h < 48) return `${h} h fa`
  return `${Math.round(h / 24)} g fa`
}

const dayKeyFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
})
/** Calendar day (YYYY-MM-DD) in Europe/Rome, the day boundary used by the writer. */
export function todayLocal(now: Date = new Date()): string {
  return dayKeyFmt.format(now)
}

export function addDays(day: string, n: number): string {
  const d = new Date(`${day}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + n)
  return d.toISOString().slice(0, 10)
}

export function daysBetween(from: string, to: string): number {
  return Math.round((Date.parse(`${to}T00:00:00Z`) - Date.parse(`${from}T00:00:00Z`)) / 86_400_000)
}

export const isDay = (s: unknown): s is string => typeof s === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(s)
