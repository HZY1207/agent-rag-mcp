# AI Agent 智能助手平台（Agent + RAG + MCP）

一个可以「聊天 → 检索知识库 → 调用工具」的智能助手平台。
核心三件套：**Agent 编排**（LangGraph）· **RAG 检索**（Qdrant）· **MCP 协议双向对接**。

## 核心能力

| 模块 | 说明 |
|---|---|
| Agent | 基于 LangGraph 的 ReAct 智能体：自主决定"检索 / 调工具"的步骤，流式输出思考与工具调用轨迹 |
| RAG | 文档上传 → 解析切片 → 向量化 → 混合检索 → 引用溯源，回答标注来源 |
| MCP 客户端 | 接入任意外部 MCP Server（filesystem、fetch、git…），工具即插即用 |
| MCP 服务端 | 把知识库检索能力暴露为标准 MCP Server，Cursor / Claude Desktop 可直接调用 |
| 会话与记忆 | 多轮对话历史持久化，上下文自动携带 |
| 聊天界面 | 工具调用过程可视化 + 引用卡片展示 |

## 技术栈

- 后端：Python 3.10+ · FastAPI · LangGraph / LangChain · MCP 官方 SDK
- 存储：Qdrant（向量库，本地模式起步）· SQLite（会话）· Redis（缓存，可选）
- 前端：Vue3 + Vite（第 8 步加入）
- 通信：SSE 流式

## 快速开始

```powershell
cd E:\work\ai-agent-mcp

# 1. 创建虚拟环境
python -m venv .venv

# 2. 激活（若报"禁止运行脚本"，见 docs/01 常见问题）
.venv\Scripts\Activate.ps1

# 3. 安装依赖
pip install -r requirements.txt

# 4. 准备配置：项目目录已带 .env（未提交到 Git），在 LLM_API_KEY= 后填入你的 Key（见 docs/02）

# 5. 启动
python -m uvicorn app.main:app --reload --port 8000
```

验证：打开 http://127.0.0.1:8000/docs 查看接口文档；访问 http://127.0.0.1:8000/api/health 应返回 `{"code":0,...}`。

## 路线图

- [x] 第 1 步：项目初始化与最小骨架
- [x] 第 2 步：LLM 接入与流式对话（SSE + Mock 模式）
- [ ] 第 3 步：RAG 检索链路（上传→切片→向量化→检索）
- [ ] 第 4 步：Agent 引擎（LangGraph ReAct + 工具调用）
- [ ] 第 5 步：MCP 客户端（接入外部工具）
- [ ] 第 6 步：MCP 服务端（知识库能力对外暴露）
- [ ] 第 7 步：会话与记忆持久化
- [ ] 第 8 步：前端聊天界面（Vue3）
- [ ] 第 9 步：工程化（语义缓存 / 限流 / Docker 部署）
- [ ] 第 10 步：评测与交付（评测集 + 演示材料）

## 文档

- [01 · 项目初始化与最小骨架](docs/01-项目初始化.md)
- [02 · LLM 接入与 SSE 流式对话](docs/02-LLM接入与SSE流式对话.md)
- [附 · Git 基础速查](docs/附-Git基础速查.md)
