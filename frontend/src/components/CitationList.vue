<script setup>
defineProps({ items: { type: Array, default: () => [] } })
</script>

<template>
  <div class="citations">
    <div class="citations-title">📚 引用来源</div>
    <div v-for="c in items" :key="c.index" class="citation-card">
      <div class="citation-head">
        <span class="cite-index">[{{ c.index }}]</span>
        <span class="cite-file">{{ c.filename }}</span>
        <span class="cite-score">相似度 {{ (c.score * 100).toFixed(1) }}%</span>
      </div>
      <div class="cite-snippet">{{ c.snippet }}</div>
    </div>
  </div>
</template>
