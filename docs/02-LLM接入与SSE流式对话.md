# 02 · LLM 接入与 SSE 流式对话

> 本步产出：`POST /api/chat`（SSE 流式）、`POST /api/chat/sync`（同步对照组）、Mock 演示模式、冒烟测试脚本
> 完成标志：不配 Key 也能看到逐字输出；填入 Key 重启后变成真实大模型回答

---

## 1. 大模型 API 长什么样：Chat Completions 协议

调用大模型本质是一次 HTTP POST，请求体是一串"消息列表"：

```json
{
  "model": "deepseek-chat",
  "messages": [
    {"role": "system",    "content": "你是一个助手"},
    {"role": "user",      "content": "你好"},
    {"role": "assistant", "content": "你好！有什么可以帮你？"},
    {"role": "user",      "content": "刚才问了什么？"}
  ],
  "stream": true
}
```

- **模型没有记忆**："多轮对话"= 把历史消息每次都重新发一遍；
- `system` 是设定角色/约束的提示词，`user` 是提问，`assistant` 是模型之前的回答；
- **OpenAI 兼容协议是事实标准**：DeepSeek、通义、智谱、Kimi 都支持，所以"换服务商"= 改 `base_url` + `model` 两个配置；
- 我们用 **LangChain 的 `ChatOpenAI`** 来调用：它是基础模型库（langchain-core）+ 各家 SDK 封装，好处是后续接 LangGraph 编排 Agent 时同一套消息抽象直接复用。

## 2. 为什么要流式：SSE 是什么

**同步 vs 流式**（想象一段 10 秒才能生成完的回答）：
- 同步：用户盯着转圈 10 秒 → 突然出现完整答案（首字延迟 = 10 秒）；
- 流式：1 秒后就看到第一个字，之后源源不断冒出来（首字延迟 = 1 秒）。

总时长几乎一样，但体验天壤之别。ChatGPT 的打字机效果就是流式。

**SSE（Server-Sent Events）**：
- 本质是一个"**永不结束的 HTTP 响应**"：响应头 `Content-Type: text/event-stream`，服务器持续往里写数据，直到写完才关闭；
- 数据按帧发送，格式固定：

```
event: delta
data: {"content": "你"}

event: delta
data: {"content": "好"}

```

- 特点：**单向**（服务器→浏览器）、纯 HTTP 不升级协议、自带断线重连；
- 对比 WebSocket：WebSocket 双向全双工、重量级；"问答型"场景数据主要是单向流，SSE 更简单够用（面试常问选型）；
- 小坑：浏览器原生 `EventSource` 只支持 GET、不能带自定义请求头，所以前端要发 POST+JWT 时用 `fetch-event-source` 库（第 8 步详解）。

**本项目的事件协议**（第 3 步会在 done 之前加入 citations）：

| 事件 | data | 含义 |
|---|---|---|
| `delta` | `{"content": "增量文本"}` | 每生成一点推一帧 |
| `done` | `{"latency_ms", "prompt_tokens", "completion_tokens", "mock"}` | 生成结束 + 用量 |
| `error` | `{"message": "..."}` | 出错 |

## 3. 代码讲解

### 3.1 `app/services/llm.py` — 模型服务封装

- **分层意义**：路由层只管"把事件转成 SSE"，不认识任何模型 SDK 细节；换模型只动这一个文件；
- **Mock 模式**：没有 Key 时逐字输出一段说明文本——学习者能先把 SSE 链路跑通，第 8 步做前端时也能先对着 Mock 联调；
- **消息组装**：`SystemMessage / HumanMessage / AIMessage` 对应三种角色；
- `stream_usage=True`：让流末尾的响应块附带 token 用量（后面要做用量统计和成本控制）。

### 3.2 `app/api/routes/chat.py` — 流式路由

- 核心是 `async generator`：**每 `yield` 一次 = 向连接里推一帧**；
- `StreamingResponse(media_type="text/event-stream")` 把生成器包成"不结束的响应"；
- 三个响应头：`Cache-Control: no-cache`（别缓存）、`X-Accel-Buffering: no`（告诉 Nginx 等反代别缓冲，否则流会被攒成一坨）；
- **异常兜底**：任何错误都转成 `error` 事件推给前端（而不是让连接静默断掉）；
- **客户端断开**：捕获 `CancelledError` 停止生成——用户关掉页面，别再烧 token 了。

### 3.3 `/api/chat/sync` — 对照组

把同一套流式生成器"攒完再返回"，就是同步接口。跑一下能直观感受两种模式的延迟差异。

## 4. 配置 API Key（位置在这里）

**文件：项目根目录 `.env`**（若不存在就从 `.env.example` 复制一份）：

```
LLM_API_KEY=            ← 把 Key 粘在这行的等号后面
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

- 改完**必须重启服务**才生效——`.env` 只在进程启动时读取一次（改 .py 代码会自动重载，是因为 `--reload` 只监听代码文件）；
- `.env` 已被 `.gitignore` 排除，**不会**被提交到 GitHub；
- DeepSeek 申请：platform.deepseek.com → 左侧 API Keys → 创建；Key 只完整显示一次，创建后立即复制；
- 换服务商对照（改 BASE_URL + MODEL 即可）：

| 服务商 | LLM_BASE_URL | LLM_MODEL 示例 |
|---|---|---|
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |
| 通义（阿里云百炼） | `https://dashscope.aliyuncs.com/compatible-mode/v1` | `qwen-plus` |
| 智谱 | `https://open.bigmodel.cn/api/paas/v4` | `glm-4-plus` |

## 5. 动手验证

**方式一（推荐）**：启动服务后，在另一个终端运行冒烟脚本：

```powershell
.venv\Scripts\python.exe -X utf8 scripts\smoke_chat.py
```

预期看到：
1. SSE 接口逐帧输出（每帧带时间戳，能看到它是"一点一点"来的，不是一口气）；
2. 同步接口的整体耗时（对比感受两者差异）。

**方式二**：curl 直接看原始 SSE 流（`-N` 表示关闭缓冲，不看会攒到最后才输出）：

```powershell
curl.exe -N -X POST http://127.0.0.1:8000/api/chat -H "Content-Type: application/json" -d "{\"message\":\"你好\"}"
```

**方式三**：`/docs` 页面里的 Try it out（注意：Swagger 页面会把整个流攒完才显示，属正常现象，不是接口问题）。

## 6. 常见问题

- **填了 Key 还是演示模式**：检查 ① `.env` 在项目根目录 ② 字段名拼写 ③ 保存后是否重启了服务；
- **401 / Invalid API key**：Key 复制不完整或已被删除；
- **404**：`LLM_BASE_URL` 少了 `/v1` 之类的路径（不同服务商路径不同，对照上表）；
- **连接超时 / Connection error**：网络到模型服务商的连接不稳定，换个时间或检查网络。

### 专题：一次真实排障——Mock 模式为什么在 Windows 上"秒吐完"

现象：SSE 接口 106 个字符 4 毫秒全部推完（服务端自测 `latency_ms=4`），同步接口却要 1.8 秒；同一份代码在测试工具里又是正常的。

排查思路：
1. 客户端逐帧时间戳挤在同一瞬间 → 先怀疑客户端缓冲，排除；
2. 服务端 `done` 事件里的 `latency_ms` 也是 4ms → 服务端"真的没花时间"，问题在服务端；
3. 给 `_mock_stream` 加临时日志打印三种时钟：`perf_counter` 前进 4ms、`monotonic` 原地不动、`loop.time()` 原地不动 → 锁定"循环时钟"；
4. `time.get_clock_info('monotonic')` 显示 Windows 上它是 `GetTickCount64()`，精度 `0.015625s`。

根因：`asyncio.sleep(0.015)` 的时长 ≤ 单调时钟精度。CPython 的 `asyncio` 在 `_run_once` 里有一句优化：**到期时刻在"当前时间 + 时钟精度"以内的定时器会被提前触发**。当事件循环持续繁忙（SSE 路径上有 Starlette 的 task group 等调度，循环从不空闲）时，每次 sleep 都被判定"已到期"立刻唤醒；同步路径循环会空闲阻塞，时钟正常前进，sleep 表现正常。

影响：只影响"用 sleep 模拟慢速输出"的演示场景。**真实大模型的流式等待来自网络 I/O（数据到达），与这个时钟精度问题无关，不受影响。**

修复：`MOCK_CHAR_DELAY` 从 0.015 提到 0.02（> 15.625ms，保证跨过一个时钟 tick）。

经验：涉及"亚 20ms 级 sleep"的代码在 Windows 上要留意时钟精度；排障时用 `perf_counter` / `monotonic` / `loop.time()` 三种时钟对照，能快速定位到"是谁的时间不对"。

## 7. 自测问题

1. SSE 和 WebSocket 的区别是什么？什么场景该选哪个？
2. 为什么改 `.env` 必须重启服务，而改 `.py` 不用？（提示：--reload 监听的什么文件）
3. Mock 模式除了"没 Key 时能用"，对开发流程还有什么价值？
4. token 用量（prompt/completion）从哪里来？为什么第 7 步要把它存进数据库？
