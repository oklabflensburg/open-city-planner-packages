<script setup lang="ts">
const open = ref(false)
const route = useRoute()
watch(() => route.fullPath, () => { open.value = false })
</script>

<template>
  <header class="sticky top-0 z-50 border-b border-white/10 bg-navy-950 text-white">
    <a href="#main-content" class="sr-only focus:not-sr-only">Skip to content</a>
    <div class="container-shell flex h-16 items-center gap-4">
      <NuxtLink to="/" class="flex shrink-0 items-center gap-2 font-bold" aria-label="Open City Planner Packages home">
        <span class="grid size-9 place-items-center rounded-lg border border-white/30 text-lg">⌬</span>
        <span class="hidden leading-tight sm:block">Open City Planner<br><span class="text-xs font-medium text-slate-300">Packages</span></span>
      </NuxtLink>
      <div class="hidden min-w-0 flex-1 lg:block"><GlobalPackageSearch compact /></div>
      <nav class="ml-auto hidden items-center gap-5 text-sm font-medium lg:flex" aria-label="Primary navigation">
        <NuxtLink to="/packages" active-class="text-brand-500">Packages</NuxtLink>
        <NuxtLink to="/publishers" active-class="text-brand-500">Publishers</NuxtLink>
        <NuxtLink to="/docs" active-class="text-brand-500">Documentation</NuxtLink>
        <NuxtLink to="/about" active-class="text-brand-500">About</NuxtLink>
        <a href="https://github.com/oklabflensburg/open-city-planner-packages" rel="noreferrer" aria-label="GitHub repository">GitHub</a>
      </nav>
      <button class="ml-auto rounded-lg p-2 lg:hidden" type="button" :aria-expanded="open" aria-controls="mobile-menu" aria-label="Toggle navigation" @click="open = !open">
        <span aria-hidden="true" class="text-2xl">{{ open ? '×' : '☰' }}</span>
      </button>
    </div>
    <div v-if="open" id="mobile-menu" class="container-shell border-t border-white/10 py-4 lg:hidden">
      <GlobalPackageSearch compact />
      <nav class="mt-4 grid gap-1" aria-label="Mobile navigation">
        <NuxtLink v-for="item in [['Packages','/packages'],['Publishers','/publishers'],['Documentation','/docs'],['About','/about']]" :key="item[1]" :to="item[1]" class="rounded-lg px-3 py-3 hover:bg-white/10">{{ item[0] }}</NuxtLink>
      </nav>
    </div>
  </header>
</template>
