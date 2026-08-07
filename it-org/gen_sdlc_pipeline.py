#!/usr/bin/env python3
"""生成 SDLC + OpenCode 融合流水线 YAML（AO schema 兼容）。

融合 OpenCode 工作流 6 阶段（Discovery → Spec → Plan → Execute → Quality → Release → Closure）
与 StaffDeck SDLC 20 员工流水线。

用法：
  python gen_sdlc_pipeline.py --out sdlc_pipeline.yaml
  python gen_sdlc_pipeline.py --project-name 订单系统 --requirements "处理订单" --no-include-ai

生成的结构与 it-org/sdlc_pipeline.yaml 一致（25 步骤 / 17 层 DAG），
可直接交给 staffdeck_orchestrator.py 执行。
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any, Optional

import yaml

# ---------------------------------------------------------------- 输入变量定义

DEFAULT_INPUTS: list[dict[str, Any]] = [
    {"name": "project_name", "default": "智能客服Agent系统",
     "comment": "项目名称"},
    {"name": "requirements", "default": "构建企业客服智能体：多轮对话、知识库问答、工单转人工、后台会话管理",
     "comment": "需求背景"},
    {"name": "include_ai", "default": "true", "comment": "是否含 AI/智能体专项模块"},
    {"name": "include_perf", "default": "false", "comment": "是否执行性能基准测试"},
    {"name": "external_release", "default": "true", "comment": "是否对外发布（决定是否走渗透测试）"},
    {"name": "skip_discovery", "default": "false", "comment": "是否跳过发现阶段（需求已明确时）"},
]

# ---------------------------------------------------------------- 步骤定义
# 结构：id / role / task / output / depends_on / depends_on_mode /
#       condition / type(approval|human_input) / prompt / max_turns
# task 中可用 {{变量}}（inputs 或上游 output）

STEPS: list[dict[str, Any]] = [
    # ================= 阶段 0 · 发现与对齐（OpenCode Phase 0） =================
    {
        "id": "discovery_ideate",
        "role": "产品经理",
        "task": (
            "项目：{{project_name}}\n"
            "需求背景：{{requirements}}\n"
            "请使用 ce-ideate 通用技能生成改进想法：分析当前需求背景，识别可改进方向，\n"
            "生成 5-10 个具体想法并按影响力评分排序。输出想法清单。"
        ),
        "output": "ideation_output",
        "condition": "{{skip_discovery}} == false",
    },
    {
        "id": "discovery_strategy",
        "role": "产品经理",
        "task": (
            "项目：{{project_name}}\n"
            "需求背景：{{requirements}}\n"
            "想法清单：{{ideation_output}}\n"
            "请使用 ce-strategy 通用技能定义产品方向：目标问题、目标用户、核心方案、\n"
            "关键指标、工作轨道。输出 STRATEGY.md 格式的策略文档。"
        ),
        "output": "strategy_output",
        "depends_on": ["discovery_ideate"],
        "condition": "{{skip_discovery}} == false",
    },
    {
        "id": "discovery_brainstorm",
        "role": "产品经理",
        "task": (
            "项目：{{project_name}}\n"
            "需求背景：{{requirements}}\n"
            "策略文档：{{strategy_output}}\n"
            "请使用 ce-brainstorm 通用技能探索需求：与用户对话澄清需求边界，\n"
            "输出需求文档（Requirements Doc），包含问题陈述、目标、验收标准、范围边界。"
        ),
        "output": "brainstorm_output",
        "depends_on": ["discovery_strategy"],
        "condition": "{{skip_discovery}} == false",
    },
    # ================= 阶段 1 · 产品 PRD + OpenSpec 提案 =================
    {
        "id": "product_prd",
        "role": "产品经理",
        "task": (
            "项目：{{project_name}}\n"
            "需求背景：{{requirements}}\n"
            "策略文档：{{strategy_output}}\n"
            "脑暴输出：{{brainstorm_output}}\n"
            "请按产品管理工作流程产出 PRD：目标用户与核心场景、功能清单与优先级、\n"
            "验收指标、里程碑与排期、风险与依赖。输出完整 PRD 文档。"
        ),
        "output": "prd",
        "depends_on": ["discovery_brainstorm"],
    },
    {
        "id": "openspec_proposal",
        "role": "产品经理",
        "task": (
            "项目：{{project_name}}\n"
            "PRD 摘要：{{prd}}\n"
            "请使用 openspec_propose_sop 技能将 PRD 转化为 OpenSpec 规范提案：\n"
            "1) 收集需求上下文与成功指标\n"
            "2) 将需求拆解为可验证的 WHEN/THEN 场景\n"
            "3) 撰写 proposal.md（含 SHALL/SHOULD/MAY 措辞的 Requirement）\n"
            "4) 干系人评审门禁\n"
            "输出 proposal.md 文档。"
        ),
        "output": "openspec_proposal_output",
        "depends_on": ["product_prd"],
    },
    # ================= 阶段 2 · 方案与架构（并行 4 员工） =================
    {
        "id": "solution_architect",
        "role": "方案架构师",
        "task": (
            "项目：{{project_name}}\n"
            "PRD 摘要：{{prd}}\n"
            "OpenSpec 提案：{{openspec_proposal_output}}\n"
            "请按智能体方案设计流程产出总体技术方案：需求拆解、Agent 架构、\n"
            "技能/知识/工具规划、实施计划、风险清单。"
        ),
        "output": "solution",
        "depends_on": ["openspec_proposal"],
    },
    {
        "id": "backend_architect",
        "role": "后端架构师",
        "task": (
            "项目：{{project_name}}\n"
            "PRD 摘要：{{prd}}\n"
            "OpenSpec 提案：{{openspec_proposal_output}}\n"
            "请按后端架构流程产出后端设计：模块划分、数据库模型、API 契约、\n"
            "技术选型与风险清单。"
        ),
        "output": "backend_design",
        "depends_on": ["openspec_proposal"],
    },
    {
        "id": "frontend_architect",
        "role": "前端开发工程师",
        "task": (
            "项目：{{project_name}}\n"
            "PRD 摘要：{{prd}}\n"
            "OpenSpec 提案：{{openspec_proposal_output}}\n"
            "请按前端工作流程产出前端方案：工程架构、组件划分、页面结构、\n"
            "与后端 API 的对接点。"
        ),
        "output": "frontend_design",
        "depends_on": ["openspec_proposal"],
    },
    {
        "id": "security_architect",
        "role": "安全架构师",
        "task": (
            "项目：{{project_name}}\n"
            "PRD 摘要：{{prd}}\n"
            "OpenSpec 提案：{{openspec_proposal_output}}\n"
            "请按安全架构流程完成威胁建模：资产清单、攻击面分析、\n"
            "安全设计评审意见与加固建议。"
        ),
        "output": "security_design",
        "depends_on": ["openspec_proposal"],
    },
    # ================= 阶段 2.5 · OpenSpec 设计 + 文档审查 =================
    {
        "id": "openspec_design",
        "role": "方案架构师",
        "task": (
            "项目：{{project_name}}\n"
            "OpenSpec 提案：{{openspec_proposal_output}}\n"
            "总体方案：{{solution}}\n"
            "后端设计：{{backend_design}}\n"
            "前端设计：{{frontend_design}}\n"
            "安全设计：{{security_design}}\n"
            "请使用 openspec_design_sop 技能将规范提案转化为设计文档：\n"
            "1) 审阅 proposal.md 规范\n"
            "2) 设计技术方案（架构/数据/接口）\n"
            "3) 撰写 design.md 与 tasks.md\n"
            "4) 使用 ce-doc-review 技能审查文档质量\n"
            "输出 design.md 和 tasks.md。"
        ),
        "output": "openspec_design_output",
        "depends_on": ["solution_architect", "backend_architect",
                       "frontend_architect", "security_architect"],
    },
    {
        "id": "architecture_approval",
        "type": "approval",
        "prompt": (
            "架构评审门禁。请确认：\n"
            "1) PRD 与四个架构方案（总体/后端/前端/安全）是否符合预期\n"
            "2) OpenSpec 设计文档（design.md/tasks.md）是否完整\n"
            "输入 y 放行进入编码阶段；输入 n 将中止流水线。"
        ),
        "depends_on": ["openspec_design"],
    },
    # ================= 阶段 3 · 实施计划（OpenCode Phase 2） =================
    {
        "id": "implementation_plan",
        "role": "方案架构师",
        "task": (
            "项目：{{project_name}}\n"
            "总体方案：{{solution}}\n"
            "OpenSpec 设计：{{openspec_design_output}}\n"
            "请使用 ce-plan 通用技能制定详细实施计划：\n"
            "1) 分解为 bite-sized 任务\n"
            "2) 每个任务标注 TDD 步骤（RED→GREEN→REFACTOR）\n"
            "3) 确定并行执行机会\n"
            "4) 输出实施计划文档\n"
            "输出 .omo/plans/<feature>-plan.md 格式的计划。"
        ),
        "output": "impl_plan",
        "depends_on": ["architecture_approval"],
    },
    # ================= 阶段 4 · 编码实现（OpenCode Phase 3，TDD 强调） =================
    {
        "id": "software_dev",
        "role": "软件工程师",
        "task": (
            "项目：{{project_name}}\n"
            "总体方案：{{solution}}\n"
            "后端设计：{{backend_design}}\n"
            "前端设计：{{frontend_design}}\n"
            "实施计划：{{impl_plan}}\n"
            "请按编码实现交付流程处理，严格遵循 TDD 工作流：\n"
            "1) 先澄清任务与验收标准\n"
            "2) 为每个任务写 FAILING 测试（RED）\n"
            "3) 实现最小代码使测试通过（GREEN）\n"
            "4) 重构（REFACTOR）\n"
            "5) 重点完成非 AI 业务模块"
        ),
        "output": "code",
        "max_turns": 6,
        "depends_on": ["implementation_plan"],
    },
    {
        "id": "ai_dev",
        "role": "AI 应用工程师",
        "task": (
            "项目：{{project_name}}\n"
            "总体方案：{{solution}}\n"
            "实施计划：{{impl_plan}}\n"
            "请按 AI 应用工程流程处理，严格遵循 TDD 工作流：\n"
            "1) 问题定义与数据审计\n"
            "2) 为关键路径写 FAILING 测试（RED）\n"
            "3) 实验迭代，实现代码（GREEN）\n"
            "4) 工程化与部署设计\n"
            "5) 重点完成 RAG/Agent 编排/Prompt 调优部分"
        ),
        "output": "ai_code",
        "max_turns": 6,
        "depends_on": ["implementation_plan"],
        "condition": "{{include_ai}} == true",
    },
    {
        "id": "devops_setup",
        "role": "DevOps 自动化工程师",
        "task": (
            "项目：{{project_name}}\n"
            "总体方案：{{solution}}\n"
            "实施计划：{{impl_plan}}\n"
            "请按 DevOps 自动化流程设计 CI/CD：构建、测试、部署流水线，\n"
            "环境管理与发布策略。确保流水线集成 TDD 测试步骤。"
        ),
        "output": "devops_plan",
        "depends_on": ["implementation_plan"],
    },
    # ================= 阶段 5 · 质量保障（OpenCode Phase 4） =================
    {
        "id": "code_review",
        "role": "代码审查专家",
        "task": (
            "项目：{{project_name}}\n"
            "待审查代码与实现说明：{{code}}\n"
            "AI 模块实现：{{ai_code}}\n"
            "请使用 ce-code-review 通用技能进行结构化代码审查：\n"
            "1) 按正确性/安全性/可维护性/性能逐项审查\n"
            "2) 用 🔴 阻塞项、🟡 建议项、💭 小改进分级标注\n"
            "3) 每条给出具体位置、原因和修改建议\n"
            "4) 区分事实与观点\n"
            "输出审查报告。"
        ),
        "output": "review_report",
        "depends_on": ["software_dev", "ai_dev"],
    },
    {
        "id": "api_test",
        "role": "API 测试工程师",
        "task": (
            "项目：{{project_name}}\n"
            "接口契约（后端设计）：{{backend_design}}\n"
            "审查报告：{{review_report}}\n"
            "请按 API 测试流程设计接口测试策略：覆盖场景、测试用例、自动化方案、监控改进。"
        ),
        "output": "api_test_plan",
        "depends_on": ["code_review"],
    },
    {
        "id": "acceptance_test",
        "role": "测试验收专员",
        "task": (
            "项目：{{project_name}}\n"
            "PRD 摘要：{{prd}}\n"
            "审查报告：{{review_report}}\n"
            "请按测试用例生成与验收清单流程产出：功能测试用例（含边界与异常）、\n"
            "验收清单、缺陷归类说明。"
        ),
        "output": "test_plan",
        "depends_on": ["code_review"],
    },
    {
        "id": "performance_test",
        "role": "性能基准工程师",
        "task": (
            "项目：{{project_name}}\n"
            "测试计划：{{test_plan}}\n"
            "请按性能基准流程产出：基准基线、压测场景、执行分析方法、性能报告模板。"
        ),
        "output": "perf_plan",
        "depends_on": ["api_test", "acceptance_test"],
        "condition": "{{include_perf}} == true",
    },
    {
        "id": "pentest",
        "role": "渗透测试工程师",
        "task": (
            "项目：{{project_name}}\n"
            "安全设计：{{security_design}}\n"
            "API 测试计划：{{api_test_plan}}\n"
            "请按渗透测试流程产出：授权范围确认、攻击面测绘、测试用例、\n"
            "报告模板与风险分级。"
        ),
        "output": "pentest_plan",
        "depends_on": ["api_test", "acceptance_test"],
        "condition": "{{external_release}} == true",
    },
    {
        "id": "release_approval",
        "type": "approval",
        "prompt": (
            "发布审批门禁。质量保障结果：\n"
            "代码审查：{{review_report}}\n"
            "API 测试：{{api_test_plan}}\n"
            "验收清单：{{test_plan}}\n"
            "输入 y 放行进入交付收尾；输入 n 中止。"
        ),
        "depends_on": ["api_test", "acceptance_test", "performance_test", "pentest"],
    },
    # ================= 阶段 6 · 发布交付（OpenCode Phase 5） =================
    {
        "id": "commit_push_pr",
        "role": "软件工程师",
        "task": (
            "项目：{{project_name}}\n"
            "代码实现：{{code}}\n"
            "AI 模块：{{ai_code}}\n"
            "测试计划：{{test_plan}}\n"
            "请使用 ce-commit-push-pr 通用技能完成发布：\n"
            "1) 使用 ce-commit 技能创建规范 commit message\n"
            "2) 推送代码到远程仓库\n"
            "3) 自动创建 PR（含描述）\n"
            "4) 记录 PR 链接\n"
            "输出发布结果。"
        ),
        "output": "release_output",
        "depends_on": ["release_approval"],
    },
    {
        "id": "delivery_summary",
        "role": "交付项目经理",
        "task": (
            "项目：{{project_name}}\n"
            "各阶段交付物：PRD={{prd}}；方案={{solution}}；代码={{code}}；\n"
            "测试={{test_plan}}；审查={{review_report}}\n"
            "发布结果：{{release_output}}\n"
            "请按项目风险巡检与周报口径汇总项目状态：进度、风险、遗留问题、\n"
            "下一步计划，输出交付总结。"
        ),
        "output": "delivery_report",
        "depends_on": ["commit_push_pr"],
    },
    # ================= 阶段 7 · 知识沉淀（OpenCode Phase 6） =================
    {
        "id": "knowledge_compound",
        "role": "知识运营专员",
        "task": (
            "项目：{{project_name}}\n"
            "交付总结：{{delivery_report}}\n"
            "请使用 ce-compound 通用技能沉淀经验：\n"
            "1) 识别本次项目中解决的技术问题\n"
            "2) 提炼可复用的模式和踩坑记录\n"
            "3) 输出到 docs/solutions/ 目录\n"
            "4) 带 YAML frontmatter 可搜索\n"
            "输出知识沉淀文档。"
        ),
        "output": "compound_output",
        "depends_on": ["delivery_summary"],
    },
    {
        "id": "knowledge_sediment",
        "role": "知识运营专员",
        "task": (
            "项目：{{project_name}}\n"
            "知识沉淀：{{compound_output}}\n"
            "交付总结：{{delivery_report}}\n"
            "请按知识沉淀流程：使用 ce-compound-refresh 技能刷新过期文档，\n"
            "识别本次项目的可复用经验与踩坑记录，\n"
            "输出知识库/SOP 修订建议清单。"
        ),
        "output": "knowledge_notes",
        "depends_on": ["knowledge_compound"],
    },
]

HEADER = """\
# SDLC + OpenCode 融合流水线 —— agency-orchestrator (AO) schema 兼容定义
# 执行器：it-org/staffdeck_orchestrator.py（把每个 step 派给 StaffDeck 数字员工）
#
# 融合 OpenCode 工作流 6 阶段（Discovery → Spec → Plan → Execute → Quality → Release → Closure）
# 与 StaffDeck SDLC 20 员工流水线。
#
# 兼容字段（AO 标准）：
#   workflow: name / agents_dir / llm / concurrency / inputs
#   step:     id / role / task / output / depends_on / depends_on_mode /
#             condition / type(approval|human_input) / prompt / loop
# 扩展字段（adapter 专用，AO 引擎会忽略，若切回 AO 需删除）：
#   extract: reply(默认) | trace —— step 结束后提取什么存进 output 变量
#   max_turns: 单会话最多轮数（SOP 采集信息需要多轮对话时用）
#
# role 字段 = StaffDeck 数字员工姓名（见 org_agents.json，SD-000~019）
# 通用技能绑定：见 org_bindings.json（ce-ideate, ce-strategy, ce-brainstorm 等）
"""


# ---------------------------------------------------------------- 构建

def build_workflow(project_name: str, requirements: str,
                   include_ai: bool, include_perf: bool,
                   external_release: bool, skip_discovery: bool = False) -> dict[str, Any]:
    """按参数构建 workflow dict。"""
    inputs = []
    for item in DEFAULT_INPUTS:
        entry = {"name": item["name"], "default": item["default"]}
        if item["name"] == "project_name":
            entry["default"] = project_name
        elif item["name"] == "requirements":
            entry["default"] = requirements
        elif item["name"] == "include_ai":
            entry["default"] = str(include_ai).lower()
        elif item["name"] == "include_perf":
            entry["default"] = str(include_perf).lower()
        elif item["name"] == "external_release":
            entry["default"] = str(external_release).lower()
        elif item["name"] == "skip_discovery":
            entry["default"] = str(skip_discovery).lower()
        inputs.append(entry)

    # 步骤全量保留；开关只反映到 inputs 默认值，由编排器运行时用 condition 跳过
    steps = [dict(s) for s in STEPS]

    return {
        "name": "sdlc-opencode-pipeline",
        "agents_dir": "./it-org",
        "llm": {
            "provider": "staffdeck",
            "retry": 3,
            "timeout": 300000,
        },
        "concurrency": 2,
        "inputs": inputs,
        "steps": steps,
    }


def render_yaml(workflow: dict[str, Any]) -> str:
    """序列化为 YAML 文本（保留字段顺序、中文字符、块标量/flow 风格）。"""
    body = yaml.dump(
        workflow, Dumper=_SDLCDumper, allow_unicode=True, sort_keys=False,
        default_flow_style=False,
    )
    body = _inject_input_comments(body)
    return HEADER + "\n" + body


# ---------------------------------------------------------------- 自定义 YAML Dumper

class _SDLCDumper(yaml.SafeDumper):
    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        return super().increase_indent(flow, False)


def _represent_str(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    if data in ("true", "false") or "{{" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


def _represent_list(dumper: yaml.SafeDumper, data: list) -> yaml.SequenceNode:
    if data and all(isinstance(x, str) for x in data):
        return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=True)
    return dumper.represent_sequence("tag:yaml.org,2002:seq", data, flow_style=False)


_SDLCDumper.add_representer(str, _represent_str)
_SDLCDumper.add_representer(list, _represent_list)

INPUT_COMMENT_RE = re.compile(r"^  - name: (\w+)\s*$")

_TOP_LEVEL_COMMENTS = [
    ("  provider: staffdeck", "        # 扩展：执行器不是 LLM，是 StaffDeck 数字员工"),
    ("  timeout: 300000", "            # 单次 turn 等待上限(ms)"),
    ("concurrency: 2", "               # 同层并行员工数"),
]


def _inject_input_comments(text: str) -> str:
    """把 DEFAULT_INPUTS 的 comment 与顶层行内注释注入到生成文本。"""
    comments = {i["name"]: i["comment"] for i in DEFAULT_INPUTS if i.get("comment")}
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        m = INPUT_COMMENT_RE.match(line)
        if m and m.group(1) in comments:
            j = i + 1
            if j < len(lines) and lines[j].lstrip().startswith("default:"):
                out.append(lines[j].rstrip("\n") + f"  # {comments[m.group(1)]}\n")
                i += 1
        i += 1
    body = "".join(out)
    for anchor, suffix in _TOP_LEVEL_COMMENTS:
        body = body.replace(anchor, anchor + suffix, 1)
    return body


# ---------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="生成 SDLC + OpenCode 融合流水线 YAML（AO schema）")
    p.add_argument("--out", default=str(Path(__file__).parent / "sdlc_pipeline.yaml"),
                   help="输出路径（默认 it-org/sdlc_pipeline.yaml）")
    p.add_argument("--project-name", default="智能客服Agent系统", help="项目名称")
    p.add_argument("--requirements", default="构建企业客服智能体：多轮对话、知识库问答、工单转人工、后台会话管理",
                   help="需求背景")
    p.add_argument("--include-ai", action="store_true", default=True,
                   help="是否含 AI/智能体专项模块（默认开）")
    p.add_argument("--no-include-ai", dest="include_ai", action="store_false")
    p.add_argument("--include-perf", action="store_true", default=False,
                   help="是否执行性能基准测试（默认关）")
    p.add_argument("--no-include-perf", dest="include_perf", action="store_false")
    p.add_argument("--external-release", action="store_true", default=True,
                   help="是否对外发布（默认开，决定是否走渗透测试）")
    p.add_argument("--no-external-release", dest="external_release", action="store_false")
    p.add_argument("--skip-discovery", action="store_true", default=False,
                   help="跳过发现阶段（需求已明确时）")
    p.add_argument("--no-skip-discovery", dest="skip_discovery", action="store_false")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    workflow = build_workflow(
        args.project_name, args.requirements,
        args.include_ai, args.include_perf, args.external_release,
        args.skip_discovery,
    )
    text = render_yaml(workflow)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    n_steps = len(workflow["steps"])
    print(f"已生成 {out}（{n_steps} 步骤）")
    print(f"  project_name: {args.project_name}")
    print(f"  include_ai={args.include_ai}, include_perf={args.include_perf}, "
          f"external_release={args.external_release}, skip_discovery={args.skip_discovery}")


if __name__ == "__main__":
    main()
