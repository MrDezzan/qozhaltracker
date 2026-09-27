/**
 * Node прячет настоящую причину сетевого сбоя внутри error.cause,
 * а наружу отдаёт бесполезное "TypeError: fetch failed".
 * Разворачиваем цепочку, чтобы в интерфейсе была видна суть.
 */
export function describeError(error: unknown): string {
  if (!(error instanceof Error)) return String(error);

  const parts: string[] = [error.message];
  let cause: unknown = (error as { cause?: unknown }).cause;
  let depth = 0;

  while (cause instanceof Error && depth < 3) {
    parts.push(cause.message);
    cause = (cause as { cause?: unknown }).cause;
    depth += 1;
  }

  const code = (error as { code?: string }).code;
  if (code) parts.push(code);

  return Array.from(new Set(parts)).join(": ");
}

const NETWORK_HINTS = [
  "fetch failed",
  "ECONNRESET",
  "ETIMEDOUT",
  "ENOTFOUND",
  "EAI_AGAIN",
  "socket hang up",
  "network",
  "terminated",
];

export function isRetriableError(error: unknown): boolean {
  const text = describeError(error).toLowerCase();
  return NETWORK_HINTS.some((hint) => text.includes(hint.toLowerCase()));
}

/**
 * Повтор при сетевых сбоях. Supabase Auth иногда обрывает соединение
 * на втором запросе подряд — один повтор снимает проблему.
 */
export async function withRetry<T>(
  operation: () => Promise<T>,
  options: { attempts?: number; delayMs?: number; sleep?: (ms: number) => Promise<void> } = {}
): Promise<T> {
  const attempts = options.attempts ?? 3;
  const delayMs = options.delayMs ?? 400;
  const sleep = options.sleep ?? ((ms: number) => new Promise((r) => setTimeout(r, ms)));

  let lastError: unknown;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await operation();
    } catch (error) {
      lastError = error;
      if (attempt === attempts || !isRetriableError(error)) {
        throw error;
      }
      await sleep(delayMs * attempt);
    }
  }
  throw lastError;
}
