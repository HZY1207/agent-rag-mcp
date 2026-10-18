<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import ToolTrace from './ToolTrace.vue'
import CitationList from './CitationList.vue'

const props = defineProps({ msg: { type: Object, required: true } })

marked.setOptions({ gfm: true, breaks: true })

// 模型输出按 Markdown 渲染，再过一遍 DOMPurify：防止模型输出里夹带恶意 HTML/脚本
const html = computed(() => DOMPurify.sanitize(marked.parse(props.msg.content || '')))
</script>

<template>
  <div class="msg" :class="msg.role">
    <div class="avatar" :class="msg.role">{{ msg.role === 'user' ? '我' : '✦' }}</div>
    <div class="bubble">
      <ToolTrace v-if="msg.steps.length" :steps="msg.steps" />

      <div v-if="msg.role === 'assistant'" class="markdown" v-html="html"></div>
      <div v-else class="plain">{{ msg.content }}</div>

      <span v-if="msg.streaming" class="caret"></span>

      <div v-if="msg.error" class="err">⚠ {{ msg.error }}</div>

      <CitationList v-if="msg.citations.length" :items="msg.citations" />

      <div v-if="msg.stats" class="stats">
        <span>⏱ {{ msg.stats.latency_ms }} ms</span>
        <span v-if="msg.stats.tool_calls">🔧 工具调用 {{ msg.stats.tool_calls }} 次</span>
        <span v-if="msg.stats.completion_tokens">🪙 {{ msg.stats.completion_tokens }} tokens</span>
        <span v-if="msg.stats.mock" class="mock-badge">演示模式</span>
      </div>
    </div>
  </div>
</template>
