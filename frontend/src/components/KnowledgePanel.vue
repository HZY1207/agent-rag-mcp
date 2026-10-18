<script setup>
import { ref, onMounted } from 'vue'
import { api } from '../api'

const emit = defineEmits(['close'])
const docs = ref([])
const uploading = ref(false)
const note = ref('')
const fileEl = ref(null)

async function refresh() {
  docs.value = await api.get('/knowledge/documents')
}

async function onFile(e) {
  const file = e.target.files?.[0]
  if (!file) return
  uploading.value = true
  note.value = ''
  try {
    const fd = new FormData()
    fd.append('file', file)
    const resp = await fetch('/api/knowledge/upload', { method: 'POST', body: fd })
    const body = await resp.json()
    if (body.code !== 0) throw new Error(body.message)
    note.value = `已入库：${body.data.filename}（${body.data.chunks} 个切片，doc_id=${body.data.doc_id}）`
    await refresh()
  } catch (err) {
    note.value = '上传失败：' + err.message
  } finally {
    uploading.value = false
    if (fileEl.value) fileEl.value.value = ''
  }
}

onMounted(refresh)
</script>

<template>
  <div class="overlay" @click.self="emit('close')">
    <div class="kb-panel">
      <header class="kb-header">
        <div>
          <h2>📚 知识库管理</h2>
          <p class="kb-sub">支持 .txt / .md / .pdf，单文件 ≤ 10MB；上传后自动切片并向量化</p>
        </div>
        <button class="kb-close" @click="emit('close')">✕</button>
      </header>

      <label class="upload-zone" :class="{ busy: uploading }">
        <input ref="fileEl" type="file" accept=".txt,.md,.pdf" hidden @change="onFile" />
        <span v-if="!uploading">点击选择文件上传</span>
        <span v-else>正在解析、切片、向量化…</span>
      </label>
      <div v-if="note" class="kb-note">{{ note }}</div>

      <div class="kb-docs">
        <div class="kb-docs-title">已入库文档（{{ docs.length }}）</div>
        <div v-for="d in docs" :key="d.doc_id" class="kb-doc">
          <span class="kb-doc-name">{{ d.filename }}</span>
          <span class="kb-doc-meta">{{ d.chunks }} 切片</span>
        </div>
        <div v-if="!docs.length" class="empty">知识库还是空的，先上传一份文档吧</div>
      </div>
    </div>
  </div>
</template>
