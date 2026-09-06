<script setup lang="ts">
usePageSeo(
  'Documentation · Open City Planner Packages',
  'Registry discovery and publishing documentation.',
  '/docs',
)
</script>
<template>
  <div class="container-shell py-12">
    <div class="mx-auto max-w-4xl">
      <p class="eyebrow">Documentation</p>
      <h1 class="page-title mt-2">Use and publish packages</h1>
      <div class="mt-10 grid gap-6 md:grid-cols-2">
        <section class="surface-card p-6">
          <h2 class="text-xl font-bold">Discover</h2>
          <p class="mt-3 leading-7 text-slate-600">
            Search packages by ID, name, publisher, classification, channel and
            version. Filter compatibility using a concrete host or SDK version.
          </p>
          <NuxtLink
            to="/packages"
            class="mt-5 inline-block font-semibold text-link-700"
            >Browse packages →</NuxtLink
          >
        </section>
        <section class="surface-card p-6">
          <h2 class="text-xl font-bold">Publish</h2>
          <p class="mt-3 leading-7 text-slate-600">
            Reviewed releases are published through the registry promotion
            process. The Package Hub reads published metadata from the Registry
            API.
          </p>
          <a
            href="https://github.com/oklabflensburg/open-city-planner-packages/blob/main/docs/publishing.md"
            class="mt-5 inline-block font-semibold text-link-700"
            >Publishing guide ↗</a
          >
        </section>
        <section id="beispiele" class="surface-card p-6 md:col-span-2">
          <h2 class="text-xl font-bold">Direct Registry access</h2>
          <p class="mt-3 text-slate-600">
            Read published modules and immutable version resources through the
            Registry API.
          </p>
          <code
            class="mt-4 block rounded-lg bg-slate-950 p-4 text-sm text-slate-100"
            >GET /api/v1/modules<br />GET /api/v1/modules/statistics<br />GET
            /api/v1/modules/statistics/versions</code
          >
        </section>
      </div>
    </div>
  </div>
</template>
