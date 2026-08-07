#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gen_c_group_tools.py
为 C 组 opencode 技能生成 StaffDeck 工具 JSON（HTTP 化 / MCP 化）。

输出: it-org/org_tools_new.json   —— 与 org_tools.json 主文件同构的 list
      it-org/C_GROUP_NOTES.md     —— 不可迁移清单与工具配置说明
"""
from __future__ import annotations

import json
from pathlib import Path

OUT_TOOLS = Path("it-org/org_tools_new.json")
OUT_NOTES = Path("it-org/C_GROUP_NOTES.md")


def http_tool(name: str, display_name: str, desc: str, bucket: str, url: str,
              method: str, token_env: str, required: list[str],
              props: dict, outputs: dict, timeout: int = 15,
              allowed_skills: list[str] | None = None) -> dict:
    return {
        "name": name,
        "display_name": display_name,
        "description": desc,
        "bucket": bucket,
        "tool_type": "http",
        "method": method,
        "url": url,
        "headers": {"Content-Type": "application/json"},
        "auth": {"type": "bearer", "token_env": token_env},
        "execution_policy": {"timeout_seconds": timeout},
        "input_schema": {"type": "object", "required": required, "properties": props},
        "output_schema": {"type": "object", "properties": outputs},
        "allowed_skills": allowed_skills or [],
        "enabled": True,
    }


def mcp_tool(name: str, display_name: str, desc: str, bucket: str,
             server: str, transport: str, command: str | None = None,
             url: str | None = None, allowed_skills: list[str] | None = None) -> dict:
    mcp_cfg: dict = {"server": server, "transport": transport}
    if command:
        mcp_cfg["command"] = command
    if url:
        mcp_cfg["url"] = url
    return {
        "name": name,
        "display_name": display_name,
        "description": desc,
        "bucket": bucket,
        "tool_type": "mcp",
        "method": "POST",
        "url": url or f"mcp://{server}",
        "headers": {},
        "auth": {},
        "mcp_config": mcp_cfg,
        "execution_policy": {"timeout_seconds": 60},
        "input_schema": {"type": "object", "properties": {}},
        "output_schema": {"type": "object", "properties": {}},
        "allowed_skills": allowed_skills or [],
        "enabled": True,
    }


def build_tools() -> list[dict]:
    tools: list[dict] = []

    # --- HTTP 化（需要真实 API 端点，占位 URL 需替换） ---
    tools.append(http_tool(
        name="image.generate.gemini",
        display_name="Gemini 图像生成",
        desc="调用 Gemini API（Nano Banana Pro）根据文本生成或编辑图像，支持风格迁移与多轮精修。原技能：ce-gemini-imagegen。",
        bucket="设计工具",
        url="https://your-gemini-proxy.example.com/v1beta/models/nano-banana:generateContent",
        method="POST",
        token_env="GEMINI_API_KEY",
        required=["prompt"],
        props={
            "prompt": {"type": "string", "description": "图像生成提示词（含风格/构图/文本要求）"},
            "mode": {"type": "string", "description": "generate 或 edit"},
            "reference_image": {"type": "string", "description": "编辑模式参考图 URL"},
        },
        outputs={"image_url": {"type": "string", "description": "生成图像地址"}},
        timeout=60,
    ))

    tools.append(http_tool(
        name="proof.doc.review",
        display_name="Proof 文档协作评审",
        desc="将 Markdown 文档共享到 Proof（proofeditor.ai），查看/评论/编辑/同步评审文档。原技能：ce-proof。",
        bucket="协作工具",
        url="https://your-proof-bridge.example.com/api/documents",
        method="POST",
        token_env="PROOF_API_TOKEN",
        required=["title", "content"],
        props={
            "title": {"type": "string", "description": "文档标题"},
            "content": {"type": "string", "description": "Markdown 内容"},
            "action": {"type": "string", "description": "share 或 sync"},
        },
        outputs={"doc_id": {"type": "string", "description": "Proof 文档 ID"}, "share_url": {"type": "string"}},
    ))

    tools.append(http_tool(
        name="product.pulse",
        display_name="产品运营脉搏",
        desc="按时间窗口拉取产品运营数据（使用量/质量/错误信号），生成 Pulse 报告。原技能：ce-product-pulse。",
        bucket="运营工具",
        url="https://your-analytics.example.com/api/pulse",
        method="POST",
        token_env="PULSE_API_TOKEN",
        required=["window"],
        props={
            "window": {"type": "string", "description": "时间窗口，如 24h / 7d"},
            "topics": {"type": "array", "items": {"type": "string"}, "description": "关注主题"},
        },
        outputs={"report": {"type": "string", "description": "Pulse 报告 Markdown"}},
        timeout=30,
    ))

    tools.append(http_tool(
        name="search.web.last30",
        display_name="近 30 天舆情检索",
        desc="检索 Reddit/X/YouTube/TikTok/HN/Polymarket/GitHub 等平台上近 30 天关于指定主题的真实讨论与帖子。原技能：last30days。",
        bucket="情报工具",
        url="https://your-search-bridge.example.com/api/last30days",
        method="POST",
        token_env="SEARCH_API_TOKEN",
        required=["topic"],
        props={
            "topic": {"type": "string", "description": "检索主题"},
            "platforms": {"type": "array", "items": {"type": "string"}, "description": "限定平台"},
            "days": {"type": "integer", "description": "回溯天数（默认 30）"},
        },
        outputs={"digest": {"type": "string", "description": "聚合检索摘要"}},
        timeout=45,
    ))

    tools.append(http_tool(
        name="trend.analyze",
        display_name="趋势分析",
        desc="分析指定主题/提示词的近期趋势信号，输出结构化趋势结论。原技能：suno-trend。",
        bucket="情报工具",
        url="https://your-trend-bridge.example.com/api/trend",
        method="POST",
        token_env="TREND_API_TOKEN",
        required=["topic"],
        props={
            "topic": {"type": "string", "description": "分析主题"},
            "window": {"type": "string", "description": "时间窗口"},
        },
        outputs={"trend_report": {"type": "string", "description": "趋势报告"}},
        timeout=30,
    ))

    # --- MCP 化（需先配置 MCPServer：/enterprise/mcp-servers 或 POST /api/enterprise/mcp-servers） ---
    tools.append(mcp_tool(
        name="slack.search",
        display_name="Slack 组织检索",
        desc="搜索 Slack 获取组织上下文（决策/约束/讨论脉络），产出综合研究摘要。原技能：ce-slack-research。需 Slack MCP Server。",
        bucket="协作工具",
        server="slack",
        transport="streamable_http",
        url="https://your-slack-mcp.example.com/mcp",
    ))

    tools.append(mcp_tool(
        name="browser.automate",
        display_name="浏览器自动化",
        desc="Playwright 浏览器自动化：导航/点击/填表/截图/抓取/QA 冒烟测试。原技能：ce-test-browser / ce-polish-beta / ce-demo-reel 的浏览器部分。需 Playwright MCP Server。",
        bucket="测试工具",
        server="playwright",
        transport="stdio",
        command="npx @playwright/mcp@latest",
    ))

    tools.append(mcp_tool(
        name="agent.browser.cli",
        display_name="Agent Browser CLI",
        desc="agent-browser 浏览器自动化 CLI 的 MCP 封装：网页交互/表单/截图/数据抓取/Electron 应用自动化。原技能：agent-browser。需 agent-browser MCP Server。",
        bucket="测试工具",
        server="agent-browser",
        transport="stdio",
        command="agent-browser mcp",
    ))

    tools.append(mcp_tool(
        name="ast.search",
        display_name="AST 结构检索",
        desc="基于抽象语法树的代码结构搜索与分析（找特定结构/模式/复杂查询），比文本 grep 更精确。原技能：ast-grep。需 ast-grep MCP Server（ast-grep 也提供本地 CLI，沙箱可用的前提下可用通用技能形态）。",
        bucket="开发工具",
        server="ast-grep",
        transport="stdio",
        command="ast-grep mcp",
    ))

    return tools


NOTES = """# C 组技能迁移说明（改装成工具）

## 已生成工具（it-org/org_tools_new.json）

### HTTP 工具（5 个，占位 URL 需替换）
| 工具名 | 原技能 | 说明 |
|---|---|---|
| image.generate.gemini | ce-gemini-imagegen | Gemini 图像生成/编辑，需要 GEMINI_API_KEY |
| proof.doc.review | ce-proof | Proof 文档协作评审，需要 PROOF_API_TOKEN |
| product.pulse | ce-product-pulse | 产品运营数据 Pulse 报告，可配定时任务 |
| search.web.last30 | last30days | 近 30 天多平台舆情检索 |
| trend.analyze | suno-trend | 主题趋势分析 |

### MCP 工具（4 个，需先创建对应 MCPServer）
| 工具名 | 原技能 | 依赖 MCPServer |
|---|---|---|
| slack.search | ce-slack-research | Slack MCP（streamable_http） |
| browser.automate | ce-test-browser / ce-polish-beta / ce-demo-reel | Playwright MCP（stdio） |
| agent.browser.cli | agent-browser | agent-browser MCP（stdio） |
| ast.search | ast-grep | ast-grep MCP（stdio） |

MCP 工具创建方式：先在 UI「/enterprise/mcp-servers」或 POST /api/enterprise/mcp-servers 注册 Server，
再创建 tool_type=mcp 的工具（mcp_config 里标注 server）。创建请求不需要 mcp_server_id（读模型才有）。

## 不可迁移（3 个，依赖本地环境/数据，无法在 StaffDeck 沙箱运行）
| 技能 | 原因 | 替代方案 |
|---|---|---|
| ce-sessions | 扫描本地 opencode session 文件 | 无（StaffDeck 自带 Trace/会话记录） |
| ce-test-xcode | 依赖本机 Xcode + 模拟器（XcodeBuildMCP） | 人工在 Mac 上跑，或接 Mac 构建机 HTTP 桥 |
| ce-demo-reel | 依赖本地录屏/终端捕获 + ffmpeg | browser.automate 截图；视频用外部录屏工具 |

## 部署注意
1. HTTP 工具 url 全部是 your-*.example.com 占位，按真实服务替换。
2. token_env 对应后端进程环境变量（如 GEMINI_API_KEY），需在 StaffDeck 部署环境注入。
3. 工具创建后默认进全局资源池（整体智能体），再通过员工绑定（resource_type=tool）授权给具体岗位。
"""


def main() -> int:
    tools = build_tools()
    OUT_TOOLS.parent.mkdir(parents=True, exist_ok=True)
    OUT_TOOLS.write_text(json.dumps(tools, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_NOTES.write_text(NOTES, encoding="utf-8")
    print(f"工具: {len(tools)} 个 → {OUT_TOOLS}")
    print(f"说明: {OUT_NOTES}")
    for t in tools:
        print(f"  [{'MCP' if t['tool_type']=='mcp' else 'HTTP'}] {t['name']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
