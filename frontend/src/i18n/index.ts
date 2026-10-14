import { it } from './it'

export type MessageKey = keyof typeof it

/**
 * Typed message lookup: a missing key is a compile error. The UI is Italian today;
 * to add a language, create another dictionary with the same keys and select it here.
 */
export function t(key: MessageKey, vars?: Record<string, string | number>): string {
  let text: string = it[key]
  if (vars) {
    for (const [k, v] of Object.entries(vars)) text = text.replaceAll(`{${k}}`, String(v))
  }
  return text
}
