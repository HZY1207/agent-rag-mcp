<script setup>
defineProps({ steps: { type: Array, default: () => [] } })
</script>

<template>
  <div class="trace">
    <details
      v-for="(s, i) in steps"
      :key="i"
      class="trace-item"
      :open="s.status === 'running'"
    >
      <summary>
        <span class="trace-dot" :class="s.status"></span>
        <span class="trace-name">{{ s.name }}</span>
        <span v-if="s.args && Object.keys(s.args).length" class="trace-args">
          {{ JSON.stringify(s.args) }}
        </span>
        <span class="trace-status">{{ s.status === 'running' ? '执行中…' : '完成' }}</span>
      </summary>
      <div v-if="s.result" class="trace-result">{{ s.result }}</div>
    </details>
  </div>
</template>
