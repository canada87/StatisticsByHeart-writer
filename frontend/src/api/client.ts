export class ApiError extends Error {
  status: number
  code: string
  retryAfter: number | null

  constructor(status: number, code: string, message: string, retryAfter: number | null = null) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.retryAfter = retryAfter
  }
}

type Params = Record<string, string | number | undefined | null>

export function withQuery(path: string, params?: Params): string {
  if (!params) return path
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `${path}?${s}` : path
}

interface Options {
  method?: 'GET' | 'POST' | 'DELETE'
  body?: unknown
  signal?: AbortSignal
}

/** Same-origin fetch. The session is an HttpOnly cookie; state-changing calls add the CSRF header. */
export async function api<T>(path: string, opts: Options = {}): Promise<T> {
  const method = opts.method ?? 'GET'
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (method !== 'GET') headers['X-SBH-Client'] = 'web'
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json'
  let res: Response
  try {
    res = await fetch(path, {
      method,
      headers,
      credentials: 'same-origin',
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    })
  } catch (err) {
    if (err instanceof DOMException && err.name === 'AbortError') throw err
    throw new ApiError(0, 'network', 'Server non raggiungibile')
  }
  if (res.status === 204) return undefined as T
  let payload: unknown = null
  try {
    payload = await res.json()
  } catch {
    /* non-JSON body */
  }
  if (!res.ok) {
    const e = (payload as { error?: { code?: string; message?: string } } | null)?.error
    const retry = res.headers.get('retry-after')
    throw new ApiError(
      res.status,
      e?.code ?? 'http_error',
      e?.message ?? res.statusText,
      retry ? Number(retry) : null,
    )
  }
  return payload as T
}
