import { t } from '../i18n'
import { fmtNumber } from './format'

export type Direction = 'up' | 'down' | 'flat' | 'none'

export interface Delta {
  direction: Direction
  pct: number | null
  /** Visible text, e.g. "+3,2% vs periodo prec." */
  text: string
  /** Screen-reader text: the direction in words, never only an arrow or a colour. */
  sr: string
}

const FLAT_BELOW_PCT = 0.5

/** Change of `current` versus `previous` as arrow-direction + text. No judgement of good/bad. */
export function describeDelta(current: number | null, previous: number | null): Delta {
  if (current === null || previous === null || previous === 0) {
    return { direction: 'none', pct: null, text: t('delta.none'), sr: t('delta.none') }
  }
  const pct = ((current - previous) / Math.abs(previous)) * 100
  if (Math.abs(pct) < FLAT_BELOW_PCT) {
    return { direction: 'flat', pct, text: t('delta.flat'), sr: t('delta.flat.sr') }
  }
  const value = fmtNumber(Math.abs(pct), 1)
  const up = pct > 0
  return {
    direction: up ? 'up' : 'down',
    pct,
    text: t(up ? 'delta.up' : 'delta.down', { value }),
    sr: t(up ? 'delta.up.sr' : 'delta.down.sr', { value }),
  }
}

/** Mean of the first third vs the last third of a series: a plain-language trend. */
export function describeTrend(values: (number | null)[]): 'up' | 'down' | 'stable' | null {
  const v = values.filter((x): x is number => x !== null)
  if (v.length < 6) return null
  const k = Math.floor(v.length / 3)
  const mean = (a: number[]) => a.reduce((s, x) => s + x, 0) / a.length
  const head = mean(v.slice(0, k))
  const tail = mean(v.slice(-k))
  if (head === 0) return null
  const pct = ((tail - head) / Math.abs(head)) * 100
  return pct > 3 ? 'up' : pct < -3 ? 'down' : 'stable'
}

/** Difference between two clock times (minutes), e.g. average bedtime now vs before. */
export function describeMinutes(current: number | null, previous: number | null): Delta {
  if (current === null || previous === null) {
    return { direction: 'none', pct: null, text: t('delta.none'), sr: t('delta.none') }
  }
  const diff = Math.round(current - previous)
  if (Math.abs(diff) < 2) return { direction: 'flat', pct: 0, text: t('delta.flat'), sr: t('delta.flat.sr') }
  const value = String(Math.abs(diff))
  return {
    direction: diff > 0 ? 'up' : 'down',
    pct: null,
    text: t(diff > 0 ? 'delta.later' : 'delta.earlier', { value }),
    sr: t(diff > 0 ? 'delta.later.sr' : 'delta.earlier.sr', { value }),
  }
}
