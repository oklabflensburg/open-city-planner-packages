<script setup lang="ts">
usePageSeo(
  'About · Open City Planner Packages',
  'How the reviewed Open City Planner Registry works.',
  '/about',
)
</script>
<template>
  <div class="container-shell py-12">
    <div class="mx-auto max-w-3xl">
      <p class="eyebrow">About</p>
      <h1 class="page-title mt-2">A transparent package registry</h1>
      <p class="mt-6 text-lg leading-8 text-slate-700">
        Open City Planner Packages makes reviewed module metadata discoverable
        without replacing the existing Git- and PR-based publishing process.
      </p>
      <div class="mt-10 grid gap-5">
        <section class="surface-card p-6">
          <h2 class="text-xl font-bold">
            Registry metadata remains authoritative
          </h2>
          <p class="mt-3 leading-7 text-slate-600">
            The Package Hub reads published modules, explicit channel pointers
            and immutable version resources from the PostgreSQL-backed Registry
            API. New publications are visible without rebuilding this frontend.
          </p>
        </section>
        <section class="surface-card p-6">
          <h2 class="text-xl font-bold">Trust without invented claims</h2>
          <p class="mt-3 leading-7 text-slate-600">
            The explorer shows publisher classification, source provenance and
            digest data that actually exists. It does not fabricate download
            counts, ratings or verification attestations.
          </p>
        </section>
      </div>
    </div>
  </div>
</template>
