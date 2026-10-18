<script setup>
defineProps({
  sessions: { type: Array, default: () => [] },
  current: { type: Object, default: null },
})
const emit = defineEmits(['select', 'create', 'remove', 'kb'])
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="logo">✦</div>
      <div>
        <div class="brand-name">AI Agent 平台</div>
        <div class="brand-sub">RAG · MCP · Agent</div>
      </div>
    </div>

    <button class="btn-new" @click="emit('create')">＋ 新建会话</button>

    <div class="sessions">
      <div
        v-for="s in sessions"
        :key="s.id"
        class="session-item"
        :class="{ active: current && current.id === s.id }"
        @click="emit('select', s)"
      >
        <div class="session-title">{{ s.title }}</div>
        <div class="session-meta">{{ s.message_count }} 条消息</div>
        <button class="session-del" title="删除会话" @click.stop="emit('remove', s)">✕</button>
      </div>
      <div v-if="!sessions.length" class="empty">还没有会话，点上面新建一个</div>
    </div>

    <button class="kb-entry" @click="emit('kb')">📚 知识库管理</button>
  </aside>
</template>
