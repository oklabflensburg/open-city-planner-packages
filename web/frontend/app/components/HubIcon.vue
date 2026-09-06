<script setup lang="ts">
defineProps<{ name: string }>()
const paths: Record<string, string> = {
  search: 'm21 21-5-5 M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0',
  cube: 'm12 2 10 5v10l-10 5L2 17V7Zm0 10 10-5M2 7l10 5v10',
  tag: 'M3 3h9l9 9-9 9-9-9Zm5 5h.01',
  users:
    'M16 21v-3a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v3M9 10a4 4 0 1 0 0-8 4 4 0 0 0 0 8M17 3a4 4 0 0 1 0 8m3 4a4 4 0 0 1 2 3v3',
  lock: 'M5 10h14v11H5Zm3 0V6a4 4 0 0 1 8 0v4',
  sun: 'M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8M12 1v2m0 18v2M1 12h2m18 0h2M4 4l2 2m12 12 2 2M4 20l2-2M18 6l2-2',
  copy: 'M9 3h12v14H9ZM6 7H3v14h12v-2',
  download: 'M12 2v13m-5-5 5 5 5-5M3 16v5h18v-5',
  star: 'm12 2 3 6 7 1-5 5 1 7-6-3-6 3 1-7-5-5 7-1Z',
  clock: 'M12 8v5l3 2M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0',
  arrow: 'M3 12h18m-6-6 6 6-6 6',
  external: 'M14 3h7v7m0-7L11 13M10 3H3v18h18v-7',
  code: 'm8 5-6 7 6 7m8-14 6 7-6 7M14 3l-4 18',
  terminal: 'm3 5 6 7-6 7m9 0h9',
  document: 'M5 2h10l4 4v16H5Zm9 0v5h5M8 12h8m-8 4h8',
  github:
    'M9 21c-5 1-5-3-7-3m14 5v-4c0-1-.2-2-1-3 4-.4 7-2 7-7 0-2-.6-3-2-4 .4-1 .4-3 0-4-2 0-4 1-5 2a16 16 0 0 0-6 0C8 2 6 1 4 1c-.4 1-.4 3 0 4-1 1-2 2-2 4 0 5 3 7 7 7-.8 1-1 2-1 3v4',
}
</script>
<template>
  <svg
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="1.7"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
    class="hub-icon"
  >
    <path :d="paths[name] || paths.cube" />
  </svg>
</template>
