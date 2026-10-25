import { isAxiosError } from "axios";

/**
 * The message the API actually returned, for showing in a toast.
 *
 * FastAPI answers with `{ detail }` — a string, or a list of validation errors.
 * Anything else falls back to the transport error, so a failure is never
 * reported as a success.
 */
/**
 * A message safe to print on the page.
 *
 * The backend's `detail` is written for whoever is calling the API, not for the
 * person reading the screen: an access failure comes back as
 * `User 'jasna.cp@futuresmart.ai' has no access to agent 'NL2SQL_39F3787E'`,
 * which was being rendered into the page body. Access and not-found failures now
 * get the caller's own wording; anything else keeps the server's message, which
 * is usually the actionable one ("could not connect to the database").
 *
 * Toasts keep using `apiMessage` — a transient notice next to an action the user
 * just took is the right place for the server's exact words.
 */
export function friendlyApiMessage(error: unknown, fallback: string): string {
  const status = isAxiosError(error) ? error.response?.status : undefined;
  if (status === 401 || status === 403 || status === 404 || status === 405) {
    return fallback;
  }
  const message = apiMessage(error);
  // A stray identifier or an internal error is not something to show either.
  return !message ||
    /NL2SQL_[0-9A-F]{8}|has no access|internal server error/i.test(message)
    ? fallback
    : message;
}

export function apiMessage(error: unknown): string {
  if (isAxiosError(error)) {
    const detail = (error.response?.data as { detail?: unknown } | undefined)
      ?.detail;

    if (typeof detail === "string") return detail;
    // `{code, message}`: the service named the case and wrote the sentence.
    if (
      detail &&
      typeof detail === "object" &&
      typeof (detail as { message?: unknown }).message === "string"
    ) {
      return (detail as { message: string }).message;
    }
    if (Array.isArray(detail)) {
      const first = detail[0] as { msg?: string; loc?: unknown[] } | undefined;
      if (first?.msg) {
        const field = Array.isArray(first.loc) ? first.loc.at(-1) : undefined;
        return field ? `${field}: ${first.msg}` : first.msg;
      }
    }
    return error.response?.statusText || error.message;
  }
  return error instanceof Error ? error.message : String(error);
}
