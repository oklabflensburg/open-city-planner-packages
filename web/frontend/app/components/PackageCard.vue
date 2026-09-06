<script setup lang="ts">
import type { PackageSummary } from '~/types/api'
defineProps<{ pkg: PackageSummary; compact?: boolean }>()
</script>
<template><PackageListItem :pkg="pkg" /></template>
