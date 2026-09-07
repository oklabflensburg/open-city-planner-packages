/** Provider URLs are external, untrusted metadata. Never render script URLs. */
export function profileUrl(value?: string | null): string | undefined {
  if (!value) return;
  try {
    const url = new URL(value);
    if (url.protocol === "https:" && !url.username && !url.password)
      return url.href;
  } catch {
    /* Missing or malformed provider metadata has no link/image. */
  }
}
export function profileDate(value?: string | null): string | undefined {
  if (!value) return;
  const date = new Date(value);
  if (!Number.isNaN(date.getTime()))
    return new Intl.DateTimeFormat("de-DE", {
      dateStyle: "medium",
      timeZone: "UTC",
    }).format(date);
}
