# 附 · Git 基础速查（含 GitHub 快速设置页面逐行讲解）

> 用于回看：GitHub 新建仓库页面上的两套命令是什么意思、我们当时执行了哪些、日常最常用的命令。
> 背景：本项目仓库 https://github.com/HZY1207/agent-rag-mcp

---

## 1. 先记住 Git 的心智模型：三个区 + 一个远端

```
工作区          暂存区            本地仓库              远端(GitHub)
你编辑文件的地方  下次提交的清单    .git 里的提交历史     origin
   │  git add  ──►  │  git commit ──►  │  git push ──►  │
   │  ◄──────────────────────────────  │  ◄── git pull ─│
```

- **工作区**：你用编辑器改文件的地方。
- **暂存区**：这次提交"准备打包"的文件清单。它的存在解决一个问题——改了 10 个文件，只想把其中 3 个放进这次提交。
- **本地仓库**：每次 `commit` 生成一个快照，有唯一 ID，可回溯。断网也能提交。
- **远端**：GitHub 上的副本。`origin` 只是给远端起的**别名**（约定俗成），因为完整地址太长。

## 2. 逐行解释：GitHub 页面上的两组命令

### 2.1 「create a new repository on the command line」= 从零开始

| 命令 | 解释 |
|---|---|
| `echo "# agent-rag-mcp" >> README.md` | 生成 README.md，内容是 Markdown 一级标题。`>>` 表示追加写入（`>` 是覆盖） |
| `git init` | 在当前目录创建本地仓库（生成隐藏的 `.git` 目录，就是 Git 的数据库） |
| `git add README.md` | 把该文件放进暂存区 |
| `git commit -m "first commit"` | 生成提交快照，附带说明 "first commit" |
| `git branch -M main` | 把当前分支改名为 `main`（老 Git 默认叫 push `master`，GitHub 默认 `main`）。一劳永逸：`git config --global init.defaultBranch main` |
| `git remote add origin <URL>` | 登记远端：别名 origin → GitHub 仓库地址 |
| `git push -u origin main` | 推送本地 main 到远端；`-u` 记录追踪关系，之后直接 `git push` 就行 |

> ⚠️ Windows PowerShell 陷阱：`echo "..." >> 文件` 在 PowerShell 5.1 中默认写出 **UTF-16 编码**，Git 会当成二进制文件处理。建议用编辑器建文件，或用 `Set-Content -Encoding utf8`。

### 2.2 「push an existing repository」= 推送已有本地仓库（**本项目用的是这组**）

| 命令 | 解释 | 我们的实际情况 |
|---|---|---|
| `git remote add origin <URL>` | 登记远端 | 推送时第一次执行 |
| `git branch -M main` | 分支改名 | 我用了 `git init -b main` 直接以 main 创建，所以这句省略 |
| `git push -u origin main` | 推送并建立追踪 | 实际执行了 `git -c http.proxy= push -u origin main`（临时绕开失效的代理配置） |

## 3. 顶部区域：HTTPS 还是 SSH？

两种"进门方式"（认证方式不同，功能完全等价）：

- **HTTPS**（我们用这个）：`https://github.com/HZY1207/agent-rag-mcp.git`
  认证交给浏览器登录（Windows Git 的凭据管理器代记），走 443 端口，走哪都能用；
- **SSH**：`git@github.com:HZY1207/agent-rag-mcp.git`
  认证靠本机生成的密钥对（公钥传到 GitHub）。国内部分网络封 22 端口，可改走 443。

其他细节：
- URL 末尾 `.git` 是裸仓库约定的后缀，加不加都能访问；
- "Set up in GitHub Desktop" = 用图形客户端完成同样的步骤，可跳过命令行。

## 4. 日常最常用的 10 条命令

| 命令 | 作用 |
|---|---|
| `git status` | 看当前状态：改了哪些、暂存了哪些 |
| `git add <文件>` / `git add -A` | 暂存单个文件 / 全部改动 |
| `git commit -m "说明"` | 提交 |
| `git log --oneline -5` | 看最近 5 条提交（一行一条） |
| `git push` | 推送（`-u` 设置过一次后无需带参数） |
| `git pull` | 拉取远端更新 |
| `git diff` | 看还没暂存的改动内容 |
| `git remote -v` | 查看远端配置 |
| `git branch` | 查看分支（当前分支带 *） |
| `git switch -c 名字` | 新建并切换到新分支 |

## 5. 本项目已踩过的坑（全部已解决）

1. **代理失效**：报错含 `via 127.0.0.1` → 代理软件没开/端口不对；可临时绕过：`git -c http.proxy= git push`；
2. **CRLF 警告**：`LF will be replaced by CRLF` 是 Windows/Linux 换行符差异提醒，无害；
3. **编码系列**：PowerShell 重定向写出 UTF-16、`requirements.txt` 被 GBK 解析等，见 `docs/01-项目初始化.md` FAQ。
