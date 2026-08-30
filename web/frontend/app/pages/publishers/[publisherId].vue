<script setup lang="ts">
const route = useRoute()
const id = String(route.params.publisherId)
const { $api } = useNuxtApp()
const { data: publisher, error } = await useAsyncData(`publisher-${id}`, () => $api.publisher(id))
if (error.value || !publisher.value) throw createError({ statusCode: 404, statusMessage: 'Publisher not found' })
usePageSeo(`${publisher.value.name} · Publishers`, `${publisher.value.name} packages in the Open City Planner Registry.`, `/publishers/${id}`)
</script>
<template><div v-if="publisher" class="container-shell py-10"><nav class="text-sm text-slate-500"><NuxtLink to="/publishers">Publishers</NuxtLink> › {{ publisher.name }}</nav><header class="mt-8 surface-card flex flex-wrap items-center gap-5 p-7"><span class="grid size-16 place-items-center rounded-full bg-navy-950 text-2xl font-bold text-white">{{ publisher.name.slice(0, 2).toUpperCase() }}</span><div class="flex-1"><h1 class="page-title">{{ publisher.name }}</h1><p class="mt-1 text-slate-500">{{ publisher.id }}</p><div class="mt-3 flex gap-2"><PackageBadge v-for="classification in publisher.classifications" :key="classification" :value="classification" /></div></div><div class="text-right"><strong class="block text-3xl">{{ publisher.package_count }}</strong><span class="text-sm text-slate-500">packages · {{ publisher.release_count }} releases</span></div></header><section class="mt-10"><h2 class="text-2xl font-bold">Packages by {{ publisher.name }}</h2><div class="mt-6 grid gap-5 md:grid-cols-2"><PackageCard v-for="pkg in publisher.packages" :key="pkg.id" :pkg="pkg" /></div></section></div></template>
