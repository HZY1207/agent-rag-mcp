"""演示用 MCP Server（stdio 传输）：提供「时间 + 文件读取」类工具。

作用：给平台第 5 步的 MCP 客户端当"外部工具服务器"——
模拟任意第三方 MCP Server（filesystem、fetch、git…）的接入方式。

单独运行（一般由 MCP 客户端自动拉起，无需手动跑）：
    .venv\\Scripts\\python.exe mcp_servers\\demo_server.py

工具：
  - get_current_time  服务器当前时间
  - list_sample_files 列出 samples 目录下的文件
  - read_text_file    读取 samples 目录下的文本文件（限定目录，防路径穿越）
"""
from datetime import datetime
from pathlib import Path

from mcp.server.mcpserver import MCPServer

# samples 目录：文件访问类工具只允许在这个"沙箱"里操作
SAMPLES_DIR = (Path(__file__).resolve().parent.parent / "samples").resolve()

mcp = MCPServer("demo-tools")


@mcp.tool()
def get_current_time() -> str:
    """获取服务器当前时间（本地时区，ISO 格式）。"""
    return datetime.now().isoformat(timespec="seconds")


@mcp.tool()
def list_sample_files() -> str:
    """列出 samples 目录下所有可读文件（名称 + 大小）。"""
    files = sorted(p for p in SAMPLES_DIR.glob("*") if p.is_file())
    if not files:
        return "samples 目录为空"
    return "\n".join(f"{p.name}（{p.stat().st_size} 字节）" for p in files)


@mcp.tool()
def read_text_file(filename: str, max_chars: int = 2000) -> str:
    """读取 samples 目录下某个文本文件的内容（最多 max_chars 个字符）。

    Args:
        filename: 文件名，例如 星尘科技员工手册.md
        max_chars: 最多返回的字符数，默认 2000
    """
    target = (SAMPLES_DIR / filename).resolve()
    # 安全检查：解析后的路径必须仍在 samples 目录内（防 ../../ 路径穿越）
    if not target.is_relative_to(SAMPLES_DIR):
        return "错误：只允许读取 samples 目录下的文件"
    if not target.is_file():
        return f"错误：文件不存在 {filename}"
    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > max_chars:
        return text[:max_chars] + f"\n…（已截断，共 {len(text)} 字符）"
    return text


if __name__ == "__main__":
    mcp.run()  # 默认 stdio 传输：由客户端进程通过标准输入输出通信
