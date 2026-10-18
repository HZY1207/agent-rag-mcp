# 04 · Agent 引擎（LangGraph ReAct + 工具调用）

> 本步新增：`app/services/agent.py`、`app/api/routes/agent.py`、`app/api/sse.py`、`scripts/smoke_agent.py`。
> 本步改动：`app/api/router.py`（注册 agent 路由）、`requirements.txt`（langchain / langgraph）。

## 一、为什么要 Agent

第 3 步的 `/api/chat` 是"固定流水线"：检索 → 拼提示词 → 回答。路径写死，简单可靠。
但真实任务经常是"走一步看一步"的：

- "年假是多少天？上限乘以 3 再减 5 等于几？" → 先查知识库，再计算，两步之间有依赖；
- "看看 samples 里有什么文件，挑一个读给我听" → 先列目录，再读文件。

固定流程没法预先知道该调几次工具、按什么顺序调。Agent 解决的就是这个问题：
**把"调用什么工具、调用几次"的决定权交给模型自己。**

| | 固定流程（第 3 步） | Agent（本步） |
|---|---|---|
| 路径 | 写死 | 模型自主决定 |
| 工具调用次数 | 固定 | 0 ~ N 次 |
| 适用场景 | 路径确定的问答 | 路径不确定、多工具协作 |
| 代价 | 便宜、可控 | token 更多、要防死循环 |

**经验法则：能用固定流程解决的，不要上 Agent。** Agent 是用成本换灵活性。

## 二、ReAct：Agent 的经典工作模式

ReAct = Reason（推理）+ Act（行动），循环往复：

```
思考：这个问题需要先查知识库
  ↓
行动：调用 search_knowledge("年假")
  ↓
观察：资料说"上限 20 天"
  ↓
思考：还需要算 20×3-5
  ↓
行动：调用 calculator("20*3-5")
  ↓
观察：55
  ↓
思考：信息够了 → 输出最终答案
```

## 三、LangGraph 与 create_agent

LangGraph 把 Agent 的执行建模成**图**：节点 = 一步计算（调模型 / 执行工具），边 = 流转方向；
"工具执行完回到模型"的那条边就是 ReAct 的循环。这样做的价值：每个节点的输出都能流式推给前端、
可中断、可持久化（后面的会话能力就建立在这套思路上）。

本项目用官方预置图：

```python
from langchain.agents import create_agent

graph = create_agent(model, tools, system_prompt=..., name="react_agent")
```

它内部就是这张图：

```
[agent 节点] ──有 tool_calls──▶ [tools 节点] ──回到──▶ [agent 节点]
      │
      └── 无 tool_calls ──▶ 结束（最终回答）
```

## 四、本步的三个工具

| 工具 | 作用 | 教学设计 |
|---|---|---|
| search_knowledge | 把第 3 步的检索能力封装成工具 | 返回带编号 `[1][2]`，与引用清单对齐 |
| calculator | 数学计算 | **安全求值**：ast 白名单，绝不用 eval |
| get_current_time | 当前时间 | 无参数工具示例 |

安全求值为什么重要：

```python
eval("__import__('os').system('rm -rf /')")   # 绝不能让模型/用户输入直接进 eval
```

`_safe_eval` 用 ast 把表达式解析成语法树，只放行「数字 + 四则运算 + 括号」节点，其余一律拒绝。
这是所有"让模型触发计算/代码"场景的底线做法。

## 五、代码走读

### 5.1 工具工厂：每请求独立 + 引用收集器

```python
def _make_tools(citations: list[dict], include_kb: bool = True) -> list:
    ...
    citations.append({"index": idx, "filename": ..., "score": ...})
```

- 工具**每次请求现构造**（闭包持有本轮 `citations`），并发请求互不污染；
- 检索结果编号**全局递增**：第一次调用 `[1][2]`、第二次 `[3][4]`……
  与推给前端的 citations 事件一一对应。

### 5.2 流式执行：两种 stream_mode

```python
async for mode, chunk in graph.astream(
    {"messages": messages},
    stream_mode=["messages", "updates"],
    config={"recursion_limit": 25},
):
    if mode == "messages":
        ...  # 模型输出流：每来一小块就转成 delta 事件（打字机效果）
    else:
        ...  # 节点更新：从 AIMessage.tool_calls 拿工具调用，从 ToolMessage 拿工具结果
```

- `messages` 模式 → 增量文本（`delta` 事件）
- `updates` 模式 → 工具调用/结果（`step` 事件）
- `recursion_limit=25`：**防死循环保险丝**（模型反复调工具不会无限转下去）

### 5.3 SSE 协议升级

| 事件 | 含义 | data |
|---|---|---|
| `step` | 工具轨迹 | `{"phase":"tool_call"/"tool_result","name",...,"args"/"summary"}` |
| `citations` | 引用列表（随检索增长，每次推全量） | `{"items":[...]}` |
| `delta` | 回答增量 | `{"content":"..."}` |
| `done` | 结束 | `latency_ms` / tokens / `tool_calls` / `mock` |
| `error` | 失败 | `{"message":"..."}` |

## 六、实测（DeepSeek 真实模型）

| 场景 | 轨迹 | 结果 |
|---|---|---|
| "星尘科技的年假是多少天？" | 模型**并行**发起 2 次检索（不同 query），引用 4 条 | 2.58s，回答正确标注 `[1][3]` |
| "（1234*7+6）/2 等于多少？" | calculator 一次 | 1.50s，4322 ✓ |
| "年假上限×3−5？先查知识库" | search → 0.8s 后 calculator("20*3-5") | 2.62s，55 ✓ |

## 七、踩坑记录

1. **过渡语泄漏**：模型会在调用工具前输出 `I'll search the knowledge base...` 混进回答流。
   解法：系统提示词明确约束"调用工具前后不要输出过渡性文字"，实测生效。
2. **API 迁移**：`langgraph.prebuilt.create_react_agent` 已在 LangGraph 1.x 弃用，
   新家是 `langchain.agents.create_agent`，系统提示词参数名也从 `prompt` 改成 `system_prompt`。
   新项目直接用新 API，别抄旧教程。
3. **Agent 的系统提示词是"行为规约"**，不是角色扮演：先用工具、编号引用、不许编造、
   别输出过渡语——约束越具体，行为越可控。

## 八、自测题

1. 什么情况下应该用固定流程而不是 Agent？举两个例子。
2. `recursion_limit=25` 防的是什么问题？不设可能发生什么？
3. 为什么工具要"每次请求现构造"而不是全局注册一次？全局注册的话引用编号会出什么问题？
4. 用一句话解释：`messages` 和 `updates` 两种流模式分别给前端提供什么？
