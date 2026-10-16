# 03 · RAG 检索链路（上传 → 切片 → 向量化 → 检索 → 带引用回答）

> 本步新增：`app/services/knowledge.py`、`app/api/routes/knowledge.py`、`app/schemas/knowledge.py`、
> `scripts/smoke_rag.py`、`samples/星尘科技员工手册.md`。
> 本步改动：`app/services/llm.py`（RAG 提示词注入）、`app/api/routes/chat.py`（citations 事件）、
> `app/core/config.py`（知识库配置项）、`app/schemas/chat.py`（`use_kb` 开关）。

## 一、这一步解决什么问题

大模型有三个硬伤：

1. **知识有截止日期**：训练完之后发生的事，它不知道；
2. **不知道你的私有数据**：公司手册、项目文档、客户资料，它都没见过；
3. **会幻觉**：不知道的时候，它会"编"一个看起来很合理的答案。

RAG（Retrieval-Augmented Generation，检索增强生成）的思路一句话：
**别让模型裸考，给它开卷。** 提问时先从你的文档库里检索出最相关的几段资料，
塞进提示词（prompt），要求模型"看着资料回答，并标注引用来源"。

和微调（Fine-tuning）对比：

| | 微调 | RAG |
|---|---|---|
| 成本 | 高（要标注数据、要算力） | 低（上传文件即可） |
| 更新知识 | 重新训练 | 换文档，即时生效 |
| 可溯源 | 难 | 容易（能给出引用） |
| 擅长 | 改风格、学格式 | 注入事实性知识 |

两者不冲突：先用 RAG 把"知道什么"解决掉，微调留给"怎么说"。

## 二、RAG 的两个阶段（本步的骨架）

```
【阶段一：离线索引】（上传文档时做一次，慢一点没关系）
  文档 ──解析──▶ 文本 ──切片──▶ 小段(chunk) ──向量化──▶ [0.12, -0.87, ..., 0.33]
                                                             │
                                                             ▼
                                                      Qdrant 向量库
                                                （向量 + 原文 + 元数据 payload）

【阶段二：在线检索 + 生成】（每次提问）
  用户问题 ──向量化──▶ 查询向量 ──相似度搜索 Top-K──▶ 最相关的 K 个 chunk
                                                          │
                       拼进 system 提示词（带编号 [1][2]...）▼
  问题 + 参考资料 ──▶ 大模型 ──▶ 带引用编号的回答 ──▶ SSE citations 事件推给前端
```

对应到接口：

- 阶段一 = `POST /api/knowledge/upload`（一个接口里把解析/切片/向量化/入库串完）
- 阶段二 = `POST /api/chat`（内部自动检索，命中资料就注入提示词并推 `citations` 事件）

## 三、四个核心概念

### 1. Embedding（向量化）：把语义变成坐标

Embedding 模型把一段文本变成一串固定长度的数字（本项目的 BGE 中文小模型：**512 维**）。
它的魔法在于：**语义相近的文本，向量在空间里的方向也相近**。

```
"年假有多少天"          → [0.21, -0.55, 0.83, ...]
"年假：入职第一年 10 天"  → [0.19, -0.52, 0.81, ...]   ← 余弦相似度很高（~0.8）
"团建预算是多少"         → [-0.44, 0.31, -0.10, ...]  ← 与上面差距明显
```

所以"相似度搜索"不需要理解语言，只需要算向量之间的**余弦相似度**——分数越接近 1 越相关。

为什么用**本地模型**（fastembed + BGE）而不是调 API？
- DeepSeek 平台**没有**提供 embedding 接口（只有对话模型）；
- 本地跑：不花钱、不依赖网络、数据不出本机（隐私）；
- fastembed 用 ONNX 推理，**不需要装 PyTorch**（省掉几个 GB），首次自动下载约几十 MB。

### 2. 切片（Chunking）：别拿整篇文章去碰瓷

整篇 5000 字的文档做成一个向量，语义会被"平均"掉，检索粒度太粗。
把文档切成 ~500 字的小段（chunk），每段一个向量，检索就能**精确到段落**。

- `chunk_size=500`、`chunk_overlap=50`：相邻切片重叠 50 字，防止一句话被切两半、语义断头；
- 切分器用 `RecursiveCharacterTextSplitter`，按「段落 → 换行 → 句号/问号/叹号 → 分号 → 逗号 → 字符」
  的优先级递归地切——**优先在自然语义边界断开**（这就是它对中文配了 `。！？；，` 分隔符的原因）。

### 3. 向量数据库（Qdrant）：专门存和搜向量的库

普通数据库按"相等"查（`WHERE id = 123`），向量库按"相似"查（"找最接近这 512 个数字的 K 行"）。

| 概念 | 类比 | 本项目 |
|---|---|---|
| Collection（集合） | 表 | `knowledge` |
| Point（点） | 一行记录 | 一个 chunk |
| Vector（向量） | 主键（但按相似度查） | 512 维 float |
| Payload（附载） | 其它字段 | doc_id / 文件名 / 页码 / 原文 |
| Distance（距离度量） | 排序规则 | Cosine 余弦 |

Qdrant 有服务端模式（Docker）和**本地模式**（`QdrantClient(path=...)`，纯文件）。
本步用本地模式：零 Docker、零额外进程，数据落在 `data/qdrant/`。
以后部署时换成 `QdrantClient(url=...)` 就行，业务代码几乎不用改。

### 4. 相似度阈值：宁缺毋滥

检索**永远**会返回 Top-K（哪怕问的是"今天天气"），但相关度低的结果注入提示词只会干扰模型。
所以加了一道闸：相似度 < `kb_score_threshold`（默认 0.43）的结果直接丢掉，
如果一个都没过线，就当普通对话处理（不注入资料、不推 citations）。

阈值不是拍脑袋定的——本步实测了这份文档的"分数底噪"：

| 问题类型 | 实测 Top-1 分数 |
|---|---|
| 打招呼 / 无关问题（"你好""今天天气"） | 0.37 ~ 0.40 |
| 相关问题（年假 / Wi-Fi / 团建） | 0.46 ~ 0.63 |

两类之间有一段空隙，阈值取空隙中点 **0.43**。换一份知识库后底噪会变，
用同样的方法（翻出几条无关问题跑一遍 `/knowledge/search` 看分数）重新量一次即可。

## 四、代码走读

### 4.1 `app/services/knowledge.py` —— RAG 核心服务

全部是**同步函数**（解析、编码、读写向量库都是 CPU/磁盘密集），由路由层
`asyncio.to_thread(...)` 丢进线程池执行。这是 async 服务里跑重活的标准姿势：
不丢线程池的话，上传一个大文档会**卡死整个事件循环**，所有并发请求都要等它。

关键函数：

| 函数 | 职责 |
|---|---|
| `_extract_pages` | 解析 txt/md/pdf → `[(页码或None, 文本)]` |
| `_split` | 递归切分成带重叠的 chunk |
| `ingest` | 解析→切片→批量向量化→写 Qdrant（幂等） |
| `search` | 问题→向量→查 Top-K，返回带分数的命中 |
| `retrieve_context` | 给对话用：过滤低分 → 组装"参考资料块 + 引用清单" |

两个设计细节值得记住：

**① 幂等入库（内容指纹做 doc_id）**

```python
doc_id = hashlib.sha1(data).hexdigest()[:12]   # 文件内容的 sha1 前 12 位
# 先按 doc_id 删旧切片，再插入新切片 → 同一文件重复上传不会产生重复数据
```

**② 懒加载单例**

向量模型（首次要下载）和 Qdrant 客户端（本地模式对目录有**文件锁**）都必须在
进程内只初始化一次，所以用模块级全局变量做懒加载单例，第一次用到才加载。

### 4.2 `app/api/routes/knowledge.py` —— 三个接口

```python
@router.post("/knowledge/upload")     # 上传入库
@router.get("/knowledge/documents")   # 已入库文档列表
@router.post("/knowledge/search")     # 纯检索（带分数，调试检索质量的最佳入口）
```

上传接口有基本的防御：扩展名白名单（txt/md/pdf）、10MB 大小上限、空文件检查。

### 4.3 `app/services/llm.py` —— 提示词注入

有资料时，system 提示词从"通用助手"切换成 RAG 版本：

```
你是知识库问答助手，请严格依据「参考资料」回答用户问题：
1. 用 [编号] 标注引用的资料（如 [1]、[2]），编号与参考资料一一对应；
2. 如果参考资料不足以回答，请明确说明「知识库中没有相关内容」……
3. 不要编造参考资料里不存在的细节。

===== 参考资料 =====
[1] 来源：星尘科技员工手册.md（全文）
年假：入职第一年 10 天……
===== 参考资料结束 =====
```

编号 `[1][2]` 与 `citations` 事件里的条目**一一对应**——前端拿到引用列表就能把
回答里的 `[1]` 渲染成可点击的来源卡片。

### 4.4 `app/api/routes/chat.py` —— citations 事件

SSE 事件协议新增一种（在 delta 之前推送）：

```
event: citations
data: {"items": [{"index": 1, "filename": "星尘科技员工手册.md", "page": null, "score": 0.72, "snippet": "年假：入职第一年 10 天……"}]}

event: delta
data: {"content": "根据公司手册[1]，"}
...
```

同步接口 `POST /api/chat/sync` 的 `data` 里也会带上 `citations` 数组。

### 4.5 新增配置项（`.env`）

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `EMBED_MODEL` | `BAAI/bge-small-zh-v1.5` | 向量模型（fastembed 标识名） |
| `HF_ENDPOINT` | `https://hf-mirror.com` | 模型下载镜像（海外可改官方地址） |
| `KB_TOP_K` | 3 | 每次检索返回条数 |
| `KB_SCORE_THRESHOLD` | 0.43 | 相似度阈值，低于此值不注入 |
| `KB_CHUNK_SIZE` / `KB_CHUNK_OVERLAP` | 500 / 50 | 切片参数 |
| `KB_COLLECTION` | knowledge | Qdrant 集合名 |

## 五、动手测试

服务启动后，一条命令跑完整链路：

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\smoke_rag.py
```

脚本做三件事：上传示例文档 → 检索"年假有多少天"看分数 → 带引用提问（包括一个
"手册里没有的问题"，观察模型如何声明不知道）。

手动玩：

```powershell
# 上传（curl.exe 的 -F 直接发 multipart 表单）
curl.exe -s -X POST http://127.0.0.1:8000/api/knowledge/upload -F "file=@samples/星尘科技员工手册.md"

# 纯检索：直接看相似度分数
curl.exe -s -X POST http://127.0.0.1:8000/api/knowledge/search -H "Content-Type: application/json" -d "{\"query\":\"报销怎么弄\",\"top_k\":3}"
```

也可以直接在 Swagger（http://127.0.0.1:8000/docs）里点。

建议观察的三件事：

1. **分数分布**：相关问题命中切片 > 0.45，打招呼/无关问题在 0.37 ~ 0.40（所以阈值定在 0.43）；
2. **回答里有 `[1]` 标注**，且 `citations` 事件在第一个 `delta` 之前到达；
3. 问手册里的问题 vs 问手册外的问题，模型的表现完全不同。

### 实测结果（本机，DeepSeek 真实模型）

| 环节 | 实测结果 |
|---|---|
| 上传入库 | 1.0 ~ 1.6s；882 字的 md 切成 2 个 chunk；doc_id=`fc19364522d1`（重复上传幂等，doc_id 不变） |
| 检索"年假有多少天" | Top-1 分数 0.5638（正确命中假期条款），第二条 0.4032 属于噪声 |
| 带引用问答（问年假） | citations 事件在 +0.36s 送达；回答 0.9s 生成完；正确复述"10 天 / 提前 3 个工作日"并标注 [1] |
| 问手册外问题（出差补贴） | 命中切片 0.5105；模型明确回答"知识库中没有相关内容"，列出手册中真实存在的相关条款，未编造 |
| 打招呼（你好） | 检索最高分 0.388 < 0.43 → 不注入资料、不推 citations，走普通对话（阈值过滤生效） |

## 六、排错专题：模型下载（国内网络必读）

fastembed 首次使用会自动下载模型。国内直连 HuggingFace 大概率不通，标准做法是走镜像：

```powershell
$env:HF_ENDPOINT='https://hf-mirror.com'   # 本项目已在配置里默认设置，无需手动
```

但镜像路上有两个坑（本步都踩过）：

**坑 1：Xet 传输后端不认镜像（401 Unauthorized）**

新版 `huggingface_hub` 对支持 Xet 协议的仓库会用"内容寻址加速下载"，
其后端域名是 `cas-server.xethub.hf.co`，**不在镜像站覆盖范围内**，直连就 401：

```
RuntimeError: CAS Client Error: ... 401 Unauthorized,
domain: https://cas-server.xethub.hf.co/...
```

解法：禁用 Xet，回退普通 HTTP 下载（本项目已在 `knowledge.py` 自动设置）：

```powershell
$env:HF_HUB_DISABLE_XET='1'
```

**坑 2：`HF_ENDPOINT` 生效时机**

`huggingface_hub` 在**模块导入时**读取 `HF_ENDPOINT` 环境变量并缓存。
所以 `knowledge.py` 把设置环境变量的代码放在**文件顶部、import fastembed 之前**——
迟一步设置就没用了。这也是为什么代码里是模块级 `os.environ.setdefault(...)` 而不是放在函数里。

另外两个小知识：

- fastembed 的模型标识名 `BAAI/bge-small-zh-v1.5` 和**实际下载仓库**不同：
  它下载的是 Qdrant 官方转换好的 ONNX 仓库 `Qdrant/bge-small-zh-v1.5`（地址在报错信息里能看到）；
- 下载偶发 `429 Rate limited`（镜像限流），huggingface_hub 自带指数退避重试，一般会自动恢复；
- 模型缓存在 `%TEMP%\fastembed_cache`（可用环境变量 `FASTEMBED_CACHE_PATH` 改位置）。

## 七、排错：Qdrant 本地模式的"文件锁"

Qdrant 本地模式对数据目录加**文件锁**：同一个 `data/qdrant` 目录，**同一时间只能被一个进程打开**。

- 症状：重启服务时报 `Storage folder ... is already accessed by another instance`；
- 原因：旧的 uvicorn 进程没退干净（比如 `--reload` 的子进程残留）；
- 解法（Windows PowerShell）：

```powershell
Get-NetTCPConnection -LocalPort 8000 -State Listen | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force }
```

然后在**同一个进程里**复用同一个 `QdrantClient`（本项目就是这么做的，别到处 new）。

这也是为什么调试脚本都通过 HTTP 接口访问服务，而不是直接打开 Qdrant 目录——
服务进程正锁着它。

## 八、自测题

1. 为什么切片要带重叠（overlap）？overlap 设太大有什么坏处？
2. `retrieve_context` 里不做相似度过滤（直接取 Top-3）会有什么后果？举一个具体场景。
3. 上传同一份文件两次，为什么不会产生重复数据？找出实现它的那几行代码。
4. 为什么 `knowledge.py` 里的函数是同步的，而路由层要 `asyncio.to_thread` 包一层？
   直接 `await` 调用会出什么问题？
5. 检索"公司的 Wi-Fi 密码"时，命中的切片恰好用的是"办公网络无线密码"这样的词，
   向量检索还能命中吗？为什么？（提示：想想 embedding 学的是"语义"还是"字面"）

> 参考答案见文末。

---

### 自测题参考要点

1. 重叠是为了防止关键句子被切在两个 chunk 的交界处、两边都不完整；overlap 太大则
   存储和编码成本上升，检索结果重复度高（一个信息被多个切片命中）。
2. 不加过滤的话，问"今天天气"也会把手册里最无关的 3 段塞给模型，模型可能被误导回答
   手册里的事，或"硬凑"引用；阈值让无关问题退回普通对话。
3. `doc_id = sha1(内容)[:12]` + 入库前 `client.delete(按 doc_id 过滤)` 再 upsert。
4. 同步函数直接 await 调用会**阻塞事件循环**：向量化是 CPU 密集型、耗时几十毫秒到几分钟
   （首次含模型下载），期间服务无法处理任何其它请求（SSE 心跳、其它对话全停）。
   `asyncio.to_thread` 把它挪到线程池，事件循环继续接客。
5. 能。embedding 学的是语义空间，"Wi-Fi 密码"和"办公网络无线密码"语义高度接近，
   即使字面不同，余弦相似度依然很高——这正是向量检索相对关键词搜索（如 SQL LIKE）的核心优势。
