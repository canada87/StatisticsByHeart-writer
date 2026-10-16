import { useNavigate, useSearch } from '@tanstack/react-router'

/** Page filters that live in the URL, so a view can be bookmarked and shared. */
function useSearchValue<V extends string>(key: string): [V | undefined, (next: V | undefined) => void] {
  const raw = useSearch({ strict: false }) as Record<string, unknown>
  const navigate = useNavigate()
  const set = (next: V | undefined) =>
    void navigate({
      to: '.',
      search: ((prev: Record<string, unknown>) => ({ ...prev, [key]: next })) as never,
    })
  return [raw[key] as V | undefined, set]
}

/** ?workouts=all shows every exercise session; the default is "real workouts only". */
export function useWorkoutScope(): ['real' | 'all', (scope: 'real' | 'all') => void] {
  const [value, set] = useSearchValue<'all'>('workouts')
  return [value === 'all' ? 'all' : 'real', (scope) => set(scope === 'all' ? 'all' : undefined)]
}

/** ?incl=1 keeps real workouts in the daytime heart rate; the default leaves them out. */
export function useIncludeWorkouts(): [boolean, (include: boolean) => void] {
  const [value, set] = useSearchValue<'1'>('incl')
  return [value === '1', (include) => set(include ? '1' : undefined)]
}
