import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '../api/client'
import { preferenceQuery } from '../api/queries'
import { type IsOn, REPORT_SECTIONS_KEY, type Selection, allOn, normalizeSelection, selectionIsOn } from './reportSections'

/**
 * The report's content choice, kept on the server (so every device sees the same). While it loads,
 * or if it cannot be read, everything is shown: a missing preference must never hide the report.
 */
export function useReportSections() {
  const qc = useQueryClient()
  const q = useQuery(preferenceQuery(REPORT_SECTIONS_KEY))
  const [saveFailed, setSaveFailed] = useState(false)
  const queryKey = preferenceQuery(REPORT_SECTIONS_KEY).queryKey
  const url = `/api/v1/preferences/${REPORT_SECTIONS_KEY}`

  // The choice is held in React state too: a controlled checkbox must change in the same event, not
  // after the server answered (the cache notifies asynchronously and the box would flicker back).
  const [local, setLocal] = useState<Selection | null>(null)
  const selection: Selection = local ?? normalizeSelection(q.data?.value)
  const isOn: IsOn = q.isPending ? allOn : selectionIsOn(selection)

  const put = useMutation({
    mutationFn: (value: Selection) => api(url, { method: 'PUT', body: { value } }),
    onSuccess: () => setSaveFailed(false),
    onError: () => setSaveFailed(true), // the page keeps the new choice until it is reloaded
  })
  const del = useMutation({
    mutationFn: () => api(url, { method: 'DELETE' }),
    onSuccess: () => setSaveFailed(false),
    onError: () => setSaveFailed(true),
  })

  const toggle = (id: string, on: boolean) => {
    const next = { ...selection, [id]: on }
    setLocal(next)
    qc.setQueryData(queryKey, { key: REPORT_SECTIONS_KEY, value: next, updated_at: null })
    put.mutate(next)
  }
  const reset = () => {
    setLocal({})
    qc.setQueryData(queryKey, { key: REPORT_SECTIONS_KEY, value: null, updated_at: null })
    del.mutate()
  }
  return { isOn, toggle, reset, loading: q.isPending, saveFailed }
}
