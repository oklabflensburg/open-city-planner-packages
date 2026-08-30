<script setup lang="ts">
const route = useRoute()
const id = String(route.params.publisherId)
const { $api } = useNuxtApp()
const { data: publisher, error } = await useAsyncData(`publisher-${id}`, () => $api.publisher(id))
if (error.value || !publisher.value) throw createError({ statusCode: 404, statusMessage: 'Publisher not found' })
usePageSeo(`${publisher.value.name} · Publishers`, `${publisher.value.name} packages in the Open City Planner Registry.`, `/publishers/${id}`)
</script>

<template><div v-if="publisher" class="container-shell py-8"><nav class="text-xs text-slate-500"><NuxtLink to="/publishers">Publishers</NuxtLink><span class="mx-2">/</span><span class="font-mono">{{ publisher.id }}</span></nav><header class="mt-6 flex flex-col gap-5 border-b border-slate-200 pb-7 sm:flex-row sm:items-center"><span class="grid size-14 place-items-center rounded-full bg-navy-950 text-xl font-bold text-white">{{ publisher.name.slice(0, 2).toUpperCase() }}</span><div class="min-w-0 flex-1"><h1 class="page-title">{{ publisher.name }}</h1><p class="mt-1 font-mono text-sm text-slate-500">{{ publisher.id }}</p><div class="mt-3 flex flex-wrap gap-2"><PackageBadge v-for="classification in publisher.classifications" :key="classification" :value="classification" /></div></div><p class="text-sm text-slate-500"><strong class="font-mono text-slate-900">{{ publisher.package_count }}</strong> packages · <strong class="font-mono text-slate-900">{{ publisher.release_count }}</strong> releases</p></header><section class="mt-8"><div class="flex items-baseline justify-between"><h2 class="text-2xl font-bold">Packages</h2><span class="text-xs text-slate-500">Published by {{ publisher.name }}</span></div><div class="mt-4 border-y border-slate-200"><PackageListItem v-for="pkg in publisher.packages" :key="pkg.id" :pkg="pkg" show-compatibility /></div></section></div></template>
