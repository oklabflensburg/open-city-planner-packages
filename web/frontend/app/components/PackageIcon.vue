<script setup lang="ts">
defineProps<{ name: string; compact?: boolean }>()
</script>
<template>
  <span class="module-icon" :class="{ compact }" aria-hidden="true"
    ><svg
      v-if="name.toLowerCase() === 'statistics'"
      viewBox="0 0 40 40"
      fill="currentColor"
    >
      <rect x="5" y="24" width="7" height="12" rx="2" />
      <rect x="17" y="15" width="7" height="21" rx="2" />
      <rect x="29" y="4" width="7" height="32" rx="2" /></svg
    ><HubIcon
      v-else
      :name="name.toLowerCase().includes('search') ? 'search' : 'cube'"
  /></span>
</template>
