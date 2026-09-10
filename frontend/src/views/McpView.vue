<script setup lang="ts">
import PlaceholderCard from '@/components/PlaceholderCard.vue'
import { MODULES } from '@/router/modules'

const meta = MODULES.find((m) => m.path === 'mcp')!
</script>

<template>
  <PlaceholderCard
    :title="meta.title"
    :description="meta.description"
    :current-stage="meta.currentStage"
  />
</template>
