export function usePageSeo(title: string, description: string, path: string) {
  const config = useRuntimeConfig()
  const canonical = `${config.public.siteUrl}${path}`
  useSeoMeta({
    title,
    description,
    ogTitle: title,
    ogDescription: description,
    ogType: 'website',
    ogUrl: canonical,
  })
  useHead({ link: [{ rel: 'canonical', href: canonical }] })
}
