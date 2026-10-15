import { useQuery } from '@tanstack/react-query'
import { useNavigate, useSearch } from '@tanstack/react-router'
import { useMemo } from 'react'
import { boundsQuery } from '../api/queries'
import { type RangePreset, type RangeSearch, type ResolvedRange, parseRangeSearch, resolveRange, toSearch } from './range'

/** The global time range, read from and written to the URL (?r=30d | ?r=custom&from=..&to=..). */
export function useRange(): [ResolvedRange, (next: { preset: RangePreset; from?: string; to?: string }) => void] {
  const raw = useSearch({ strict: false }) as Record<string, unknown>
  const navigate = useNavigate()
  const parsed: RangeSearch = parseRangeSearch(raw)
  const bounds = useQuery({ ...boundsQuery(), enabled: parsed.r === 'all' })
  const firstDay = bounds.data?.first
  const range = useMemo(
    () => resolveRange(parsed, undefined, firstDay),
    [parsed.r, parsed.from, parsed.to, firstDay], // eslint-disable-line react-hooks/exhaustive-deps
  )
  const setRange = (next: { preset: RangePreset; from?: string; to?: string }) => {
    void navigate({
      to: '.',
      search: ((prev: Record<string, unknown>) => ({
        ...prev,
        r: undefined,
        from: undefined,
        to: undefined,
        ...toSearch(next),
      })) as never,
    })
  }
  return [range, setRange]
}
