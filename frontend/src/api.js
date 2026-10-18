/* ========== API 封装 ========== */

async function request(method, path, body) {
  const resp = await fetch('/api' + path, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await resp.json().catch(() => ({ code: resp.status, message: resp.statusText }))
  if (data.code !== 0) throw new Error(data.message || '请求失败')
  return data.data
}

export const api = {
  get: (path) => request('GET', path),
  post: (path, body) => request('POST', path, body),
  patch: (path, body) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),
}

/**
 * 消费 Agent 的 SSE 流。
 * fetch 没法用 EventSource（只支持 GET），所以手动读 ReadableStream 并按帧解析：
 *   event: xxx\r?\ndata: {...}\r?\n\r?\n
 */
export async function streamAgentChat(body, handlers, signal) {
  const resp = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!resp.ok || !resp.body) throw new Error(`HTTP ${resp.status}`)

  const reader = resp.body.getReader()
  const decoder = new TextDecoder('utf-8')
  let buffer = ''

  const dispatch = (frame) => {
    let event = 'message'
    const dataLines = []
    for (const raw of frame.split(/\r?\n/)) {
      if (raw.startsWith('event:')) event = raw.slice(6).trim()
      else if (raw.startsWith('data:')) dataLines.push(raw.slice(5).trim())
    }
    if (!dataLines.length) return
    let payload
    try {
      payload = JSON.parse(dataLines.join('\n'))
    } catch {
      return
    }
    handlers[event]?.(payload)
  }

  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let match
    while ((match = buffer.match(/\r?\n\r?\n/))) {
      const frame = buffer.slice(0, match.index)
      buffer = buffer.slice(match.index + match[0].length)
      if (frame.trim()) dispatch(frame)
    }
  }
}
