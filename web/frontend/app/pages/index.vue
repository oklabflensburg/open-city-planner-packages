<script setup lang="ts">
const { $api } = useNuxtApp()
const { data } = await useAsyncData('featured-packages', () => $api.packages({ limit: 4, sort: 'name' }))
usePageSeo('Open City Planner Packages', 'Discover secure, verified and compatible Open City Planner modules.', '/')
const benefits = [
  ['Verified & secure', 'Reviewed metadata, immutable SHA-256 digests and a controlled publishing pipeline.'],
  ['Compatible', 'Host, SDK and module requirements are visible before download.'],
  ['Transparent', 'Open source, license and provenance remain part of every release.'],
  ['Community driven', 'First-party and reviewed-community packages share one Registry v1 contract.'],
]
</script>
<template>
  <div>
    <section class="relative overflow-hidden bg-navy-950 text-white">
      <div class="absolute inset-0 opacity-20" style="background-image: radial-gradient(circle at 75% 20%, #22c55e 0, transparent 22%), linear-gradient(135deg, transparent 45%, #1e3a5f 46%, transparent 47%)" />
      <div class="container-shell relative grid min-h-[500px] items-center py-16 lg:grid-cols-[1fr_0.8fr]">
        <div class="max-w-2xl"><p class="eyebrow text-brand-500">Registry v1 package explorer</p><h1 class="mt-5 text-4xl font-bold tracking-tight sm:text-6xl">Discover and use<br>Open City Planner <span class="text-brand-500">modules</span></h1><p class="mt-6 max-w-xl text-lg leading-8 text-slate-300">A registry of secure, verified and compatible modules for the Open City Planner ecosystem.</p><div class="mt-8 max-w-xl"><GlobalPackageSearch /></div><div class="mt-6 flex flex-wrap gap-3"><NuxtLink to="/packages" class="primary-button">Browse all packages</NuxtLink><NuxtLink to="/docs" class="inline-flex items-center px-4 py-3 font-semibold text-white">Publish a module →</NuxtLink></div></div>
      </div>
    </section>
    <section class="container-shell py-14"><div class="flex items-end justify-between"><div><p class="eyebrow">Reviewed releases</p><h2 class="mt-2 text-2xl font-bold">Featured packages</h2></div><NuxtLink to="/packages" class="text-sm font-semibold text-link-700">View all packages →</NuxtLink></div><div class="mt-7 grid gap-5 md:grid-cols-2 xl:grid-cols-4"><PackageCard v-for="pkg in data?.items || []" :key="pkg.id" :pkg="pkg" compact /></div></section>
    <section class="container-shell pb-6"><div class="surface-card p-7 sm:p-10"><p class="eyebrow">Built for confidence</p><h2 class="mt-2 text-2xl font-bold">Why Open City Planner Packages?</h2><div class="mt-8 grid gap-8 sm:grid-cols-2 lg:grid-cols-4"><article v-for="(benefit, index) in benefits" :key="benefit[0]"><div class="grid size-10 place-items-center rounded-lg bg-slate-100 font-bold text-brand-700">{{ index + 1 }}</div><h3 class="mt-4 font-bold">{{ benefit[0] }}</h3><p class="mt-2 text-sm leading-6 text-slate-600">{{ benefit[1] }}</p></article></div></div></section>
  </div>
</template>
