/**
 * Copies text, resolving to whether it worked.
 *
 * `navigator.clipboard` rejects when the page is not a secure context or the
 * permission is denied, and an uncaught rejection there would surface as a page
 * error — so every copy in the app goes through here and reports the failure to
 * the caller instead.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard?.writeText(text);
    return true;
  } catch {
    return false;
  }
}
