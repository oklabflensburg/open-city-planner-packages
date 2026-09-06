import type { PackageRelease } from '~/types/api'
export function safeUrl(value: string | null | undefined): string | undefined {
  if (!value) return
  try {
    const url = new URL(value)
    if (
      ['https:', 'http:'].includes(url.protocol) &&
      !url.username &&
      !url.password
    )
      return url.href
  } catch {
    /* No usable URL. */
  }
}
export function repositoryLinks(value: string) {
  const source = safeUrl(value)
  if (!source) return {}
  const url = new URL(source)
  const match =
    url.hostname === 'github.com' &&
    !url.port &&
    url.pathname.match(/^\/([\w.-]+)\/([\w.-]+)\/?$/)
  if (!match) return { source, label: url.hostname + url.pathname }
  const path = `${match[1]}/${match[2]!.replace(/\.git$/, '')}`
  return {
    source,
    label: path,
    issues: `https://github.com/${path}/issues`,
    releases: `https://github.com/${path}/releases`,
  }
}
export function installCommand(id: string, release?: PackageRelease) {
  return release
    ? `ocp module install-registry ${id} \\
  --version ${release.version} \\
  --expected-sha256 ${release.artifact.sha256}`
    : `ocp module install-registry ${id}`
}
export function publicationDate(value: string | null | undefined) {
  if (!value) return 'Nicht verfügbar'
  return new Intl.DateTimeFormat('de-DE', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
    timeZone: 'UTC',
  }).format(new Date(value))
}
export function apiErrorStatus(error: unknown): number {
  const e = error as {
    statusCode?: number
    status?: number
    response?: { status?: number }
  } | null
  return (e?.statusCode || e?.status || e?.response?.status) === 404 ? 404 : 503
}
