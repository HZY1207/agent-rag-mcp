<script setup>
import SessionSidebar from './components/SessionSidebar.vue'
import ChatMessage from './components/ChatMessage.vue'
import KnowledgePanel from './components/KnowledgePanel.vue'
import { api, streamAgentChat } from './api'
import { ref, onMounted, nextTick } from 'vue'

const sessions = ref([])
const currentSession = ref(null)
const messages = ref([])
const input = ref('')
const sending = ref(false)
const kbOpen = ref(false)
const toast = ref('')
const listEl = ref(null)
let abortCtrl = null

function showToast(msg) {
  toast.value = msg
  setTimeout(() => (toast.value = ''), 2600)
}

function scrollToBottom() {
  nextTick(() => {
    const el = listEl.value
    if (el) el.scrollTop = el.scrollHeight
  })
}

async function loadSessions() {
  sessions.value = await api.get('/sessions')
}

async function selectSession(s) {
  if (sending.value) return
  currentSession.value = s
  const detail = await api.get(`/sessions/${s.id}`)
  messages.value = (detail.messages || []).map((m, i) => ({
    id: `h-${i}`,
    role: m.role,
    content: m.content,
    citations: m.citations || [],
    steps: [],
    stats: null,
    streaming: false,
    error: '',
  }))
  scrollToBottom()
}

async function newSession() {
  if (sending.value) return
  const s = await api.post('/sessions', {})
  await loadSessions()
  currentSession.value = s
  messages.value = []
  showToast('已创建新会话')
}

async function removeSession(s) {
  if (!confirm(`删除会话「${s.title}」？`)) return
  try {
    await api.del(`/sessions/${s.id}`)
    if (currentSession.value?.id === s.id) {
      currentSession.value = null
      messages.value = []
    }
    await loadSessions()
    showToast('会话已删除')
  } catch (e) {
    showToast('删除失败：' + e.message)
  }
}

async function send() {
  const text = input.value.trim()
  if (!text || sending.value) return
  if (!currentSession.value) await newSession()
  if (!currentSession.value) return

  input.value = ''
  sending.value = true
  messages.value.push({
    id: `u-${Date.now()}`,
    role: 'user',
    content: text,
    citations: [],
    steps: [],
    stats: null,
    streaming: false,
    error: '',
  })
  const idx =
    messages.value.push({
      id: `a-${Date.now()}`,
      role: 'assistant',
      content: '',
      citations: [],
      steps: [],
      stats: null,
      streaming: true,
      error: '',
    }) - 1
  const msg = messages.value[idx]
  scrollToBottom()

  abortCtrl = new AbortController()
  try {
    await streamAgentChat(
      { message: text, session_id: currentSession.value.id },
      {
        // 工具轨迹：tool_call 进"执行中"，tool_result 回填结果
        step: (d) => {
          if (d.phase === 'tool_call') {
            msg.steps.push({ name: d.name, args: d.args || {}, result: '', status: 'running' })
          } else {
            const running = [...msg.steps].reverse().find((s) => s.name === d.name && s.status === 'running')
            if (running) {
              running.result = d.summary || ''
              running.status = 'done'
            } else {
              msg.steps.push({ name: d.name, args: {}, result: d.summary || '', status: 'done' })
            }
          }
          scrollToBottom()
        },
        citations: (d) => {
          msg.citations = d.items || []
          scrollToBottom()
        },
        delta: (d) => {
          msg.content += d.content || ''
          scrollToBottom()
        },
        done: (d) => {
          msg.stats = d
        },
        error: (d) => {
          msg.error = d.message || '生成失败'
        },
      },
      abortCtrl.signal,
    )
  } catch (e) {
    if (e.name !== 'AbortError') msg.error = '请求失败：' + (e.message || e)
  } finally {
    msg.streaming = false
    sending.value = false
    abortCtrl = null
    try {
      await loadSessions()
      const updated = sessions.value.find((x) => x.id === currentSession.value?.id)
      if (updated) currentSession.value = updated
    } catch {
      /* 列表刷新失败不影响本轮对话 */
    }
  }
}

function stop() {
  abortCtrl?.abort()
}

function onKeydown(e) {
  // Enter 发送，Shift+Enter 换行
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

onMounted(async () => {
  await loadSessions()
  if (sessions.value.length) {
    await selectSession(sessions.value[0])
  } else {
    await newSession()
  }
})
</script>

<template>
  <div class="app">
    <SessionSidebar
      :sessions="sessions"
      :current="currentSession"
      @create="newSession"
      @select="selectSession"
      @remove="removeSession"
      @kb="kbOpen = true"
    />

    <main class="main">
      <header class="chat-header">
        <div class="chat-title">
          {{ currentSession?.title || '新会话' }}
          <span class="chat-sub">Agent · RAG · MCP</span>
        </div>
        <div class="chat-status"><span class="pulse"></span>服务在线</div>
      </header>

      <div ref="listEl" class="chat-list">
        <div v-if="!messages.length" class="welcome">
          <div class="welcome-logo">✦</div>
          <h1>AI Agent 智能助手平台</h1>
          <p>Agent 会自主调用知识库检索、计算器与 MCP 外部工具来回答问题。</p>
          <div class="examples">
            <button @click="input = '星尘科技的年假是多少天？需要提前多久申请？'">
              公司年假政策是什么？
            </button>
            <button @click="input = '帮我算一下：（1234*7+6）/2 等于多少？'">
              （1234*7+6）/2 等于多少？
            </button>
            <button @click="input = '看看 samples 目录里有哪些文件？'">
              samples 目录里有哪些文件？
            </button>
          </div>
        </div>

        <ChatMessage v-for="m in messages" :key="m.id" :msg="m" />
      </div>

      <footer class="composer">
        <textarea
          v-model="input"
          rows="2"
          placeholder="输入问题，Enter 发送，Shift+Enter 换行…"
          @keydown="onKeydown"
        ></textarea>
        <button v-if="!sending" class="send-btn" :disabled="!input.trim()" @click="send">发送</button>
        <button v-else class="send-btn stop" @click="stop">停止</button>
      </footer>
    </main>

    <KnowledgePanel v-if="kbOpen" @close="kbOpen = false" />

    <transition name="fade">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </transition>
  </div>
</template>
