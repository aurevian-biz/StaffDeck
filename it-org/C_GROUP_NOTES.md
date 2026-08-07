# C 组技能迁移说明（改装成工具）

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
