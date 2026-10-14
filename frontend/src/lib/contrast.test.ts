import { readFileSync } from 'node:fs'
import { join } from 'node:path'
import { describe, expect, it } from 'vitest'

// Tokens are parsed straight from the CSS (single source of truth).
const css = readFileSync(join(import.meta.dirname, '..', 'styles', 'index.css'), 'utf8')
const token = (name: string): string => {
  const m = css.match(new RegExp(String.raw`--color-${name}:\s*(#[0-9a-fA-F]{6})`))
  if (!m?.[1]) throw new Error(`token ${name} not found`)
  return m[1]
}

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  }) as [number, number, number]
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}
export function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number]
  return (hi + 0.05) / (lo + 0.05)
}

const BACKGROUNDS = ['bg', 'surface', 'surface-muted'] as const

describe('PROJECT_GUIDE 8.5: contrast', () => {
  const text = ['fg', 'fg-muted', 'accent-text', 'danger-text', 'warn', 'ok', 'm-heart', 'm-sleep-text', 'm-activity', 'm-energy', 'm-vitals', 'accent-glow']
  for (const bg of BACKGROUNDS) {
    for (const fg of text) {
      it(`text ${fg} on ${bg} >= 4.5:1`, () => {
        expect(contrast(token(fg), token(bg))).toBeGreaterThanOrEqual(4.5)
      })
    }
  }

  for (const bg of BACKGROUNDS) {
    it(`control border on ${bg} >= 3:1`, () => {
      expect(contrast(token('border-control'), token(bg))).toBeGreaterThanOrEqual(3)
    })
    it(`accent fill on ${bg} >= 3:1`, () => {
      expect(contrast(token('accent'), token(bg))).toBeGreaterThanOrEqual(3)
    })
    it(`chart colour m-sleep on ${bg} >= 3:1`, () => {
      expect(contrast(token('m-sleep'), token(bg))).toBeGreaterThanOrEqual(3)
    })
  }

  it('black text on the accent button >= 4.5:1', () => {
    expect(contrast('#000000', token('accent'))).toBeGreaterThanOrEqual(4.5)
  })
})
