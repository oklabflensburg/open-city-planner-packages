<script setup lang="ts">
const props = defineProps<{
  value: string
  label: string
  truncate?: boolean
  block?: boolean
}>()
const message = ref('')
let timer: ReturnType<typeof setTimeout> | undefined
async function copy() {
  try {
    await navigator.clipboard.writeText(props.value)
    message.value = 'Kopiert'
  } catch {
    message.value = 'Kopieren nicht möglich. Bitte Text markieren.'
  }
  clearTimeout(timer)
  timer = setTimeout(() => {
    message.value = ''
  }, 2500)
}
onBeforeUnmount(() => clearTimeout(timer))
</script>
<template>
  <span class="copy-value" :class="{ 'code-block': block }"
    ><span v-if="block" class="code-language">bash</span
    ><code
      :class="{ truncated: truncate }"
      :title="truncate ? value : undefined"
      >{{ value }}</code
    ><button type="button" :aria-label="`${label} kopieren`" @click="copy">
      <HubIcon name="copy" /></button
    ><span class="copy-status" role="status">{{ message }}</span></span
  >
</template>
