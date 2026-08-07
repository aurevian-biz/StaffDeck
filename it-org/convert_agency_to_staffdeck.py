#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_agency_to_staffdeck.py
==============================
将 agency-agents-zh（https://github.com/jnMetaCode/agency-agents-zh）的
AI 专家角色 Markdown 批量转化为 StaffDeck 数字员工配置。

转化映射：
  frontmatter name/description       -> 员工 name/description
  ## 身份与记忆 / ## 核心使命 / ## 关键规则 -> persona_prompt
  ## 工作流程（步骤 1..N）            -> SOP SkillCard 节点 + 边（线性状态机）
  frontmatter emoji                  -> avatar_preset 参考

输出：
  it-org/org_agents_new.json        员工数组（可直接并入 org_agents.json）
  it-org/org_skills_new.json        SOP 数组（可直接并入 org_skills.json）
  it-org/org_bindings_new.json      绑定数组（可直接并入 org_bindings.json）

用法：
  python3 it-org/convert_agency_to_staffdeck.py [角色目录] [输出目录]
  默认角色目录 /tmp/opencode/agency_roles，输出目录 it-org/
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 角色映射表：文件 slug -> 员工与 SOP 配置
# ---------------------------------------------------------------------------
ROLE_MAP = [
    {
        "file": "engineering-code-reviewer.md",
        "agent": {
            "name": "代码审查专家",
            "description": "专业代码审查专家，提供建设性、可操作的反馈，聚焦正确性、可维护性、安全性和性能。",
            "role_name": "代码审查专家",
            "role_key": "code_review_expert",
            "department": "研发部",
            "team": "质量保障组",
            "employee_no": "SD-009",
        },
        "sop": {
            "skill_id": "code_review_expert_sop",
            "name": "代码审查流程",
            "business_domain": "engineering",
            "trigger_intents": ["代码审查", "review", "审查代码", "PR 检查", "帮我看看这段代码"],
            "bind": ["tech_knowledge"],
            # 该角色文件无「工作流程」章节，显式定义步骤
            "workflow": {
                "steps": ["收集代码与审查上下文", "按正确性/安全性/可维护性/性能逐项审查", "分级标注审查意见", "交付审查报告与改进建议"],
                "details": [
                    ["获取待审查的代码、PR 变更或文件路径，确认审查范围（单文件/模块/整个 PR）"],
                    ["逐一检查正确性（是否实现预期功能）、安全性（注入/鉴权绕过/数据泄露）、可维护性（命名/结构/重复代码）、性能（N+1 查询/资源泄漏）"],
                    ["用 🔴 阻塞项、🟡 建议项、💭 小改进分级标注，每条给出具体位置、原因和修改建议，表扬写得好的代码"],
                    ["一次输出完整审查意见，区分事实与观点；阻塞项明确说明必须修复的理由，建议项给出优先级"],
                ],
            },
        },
    },
    {
        "file": "engineering-backend-architect.md",
        "agent": {
            "name": "后端架构师",
            "description": "资深后端架构师，专精可扩展系统设计、数据库架构、API 开发和云基础设施。",
            "role_name": "后端架构师",
            "role_key": "backend_architect",
            "department": "研发部",
            "team": "架构组",
            "employee_no": "SD-010",
        },
        "sop": {
            "skill_id": "backend_architect_sop",
            "name": "后端架构设计流程",
            "business_domain": "engineering",
            "trigger_intents": ["架构设计", "系统设计", "后端架构", "数据库设计", "微服务设计"],
            "bind": ["tech_knowledge"],
            "workflow": {
                "steps": ["收集需求与约束", "设计系统架构与服务分解", "设计数据库与 API 规范", "交付架构文档与风险清单"],
                "details": [
                    ["确认业务目标、用户规模、性能要求（延迟/吞吐量）、现有系统约束、安全合规要求"],
                    ["设计可水平扩展的微服务或模块化架构，明确服务边界、通信方式（REST/事件驱动）、缓存与扩展策略"],
                    ["设计数据库 schema 与索引（10 万+ 实体规模）、API 契约与版本策略、认证授权方案、监控告警"],
                    ["输出高层架构图、服务分解说明、数据库/API 设计、部署与容灾方案、风险清单，默认包含安全与监控设计"],
                ],
            },
        },
    },
    {
        "file": "testing-api-tester.md",
        "agent": {
            "name": "API 测试工程师",
            "description": "专注于全面 API 验证、性能测试和质量保证的 API 测试专家，覆盖所有系统和第三方集成。",
            "role_name": "API 测试工程师",
            "role_key": "api_tester",
            "department": "测试部",
            "team": "测试组",
            "employee_no": "SD-011",
        },
        "sop": {
            "skill_id": "api_testing_sop",
            "name": "API 测试流程",
            "business_domain": "testing",
            "trigger_intents": ["API 测试", "接口测试", "测试用例", "接口验证", "API 集成测试"],
            "bind": ["tech_knowledge", "test_standards"],
        },
    },
    {
        "file": "testing-performance-benchmarker.md",
        "agent": {
            "name": "性能基准工程师",
            "description": "专注系统性能测试和容量规划的性能工程专家，用数据找到性能瓶颈，用基准测试证明优化效果。",
            "role_name": "性能基准工程师",
            "role_key": "performance_benchmarker",
            "department": "测试部",
            "team": "性能组",
            "employee_no": "SD-012",
        },
        "sop": {
            "skill_id": "performance_benchmark_sop",
            "name": "性能基准测试流程",
            "business_domain": "testing",
            "trigger_intents": ["性能测试", "压测", "基准测试", "性能优化", "容量规划"],
            "bind": ["tech_knowledge", "test_standards"],
        },
    },
    {
        "file": "engineering-devops-automator.md",
        "agent": {
            "name": "DevOps 自动化工程师",
            "description": "精通基础设施自动化、CI/CD 流水线开发和云运维的 DevOps 专家。",
            "role_name": "DevOps 自动化工程师",
            "role_key": "devops_automator",
            "department": "研发部",
            "team": "平台工程组",
            "employee_no": "SD-013",
        },
        "sop": {
            "skill_id": "devops_automation_sop",
            "name": "DevOps 自动化流程",
            "business_domain": "engineering",
            "trigger_intents": ["CI/CD", "DevOps", "部署流水线", "基础设施自动化", "自动化运维"],
            "bind": ["tech_knowledge"],
        },
    },
    {
        "file": "engineering-ai-engineer.md",
        "agent": {
            "name": "AI 应用工程师",
            "description": "精通机器学习模型开发与部署的 AI 工程专家，擅长从数据处理到模型上线的全链路工程化，专注构建可靠、可扩展的 AI 系统。",
            "role_name": "AI 应用工程师",
            "role_key": "ai_app_engineer",
            "department": "研发部",
            "team": "AI 应用组",
            "employee_no": "SD-014",
        },
        "sop": {
            "skill_id": "ai_app_engineer_sop",
            "name": "AI 应用工程流程",
            "business_domain": "ai_engineering",
            "trigger_intents": ["AI 应用", "模型开发", "RAG 方案", "Prompt 设计", "LLM 应用", "模型部署"],
            "bind": ["tech_knowledge"],
            # 角色文件有「工作流程」章节，显式覆盖以获得更干净的节点名
            "workflow": {
                "steps": ["问题定义与数据审计", "实验迭代", "工程化与部署", "线上验证与迭代"],
                "details": [
                    ["明确业务目标和评估指标，定义在什么数据集、什么场景下；数据质量审计（分布、缺失值、标注一致性）；确定 baseline：规则方案或已有模型的效果"],
                    ["搭建可复现的实验管线（随机种子、环境依赖、数据版本全部锁定）；快速迭代：先跑通 pipeline 再优化单点；离线评估要全面：precision/recall/F1 之外关注分布外样本和边界情况"],
                    ["模型打包：Docker 镜像 + 模型权重版本化；性能优化：推理延迟和吞吐量满足 SLA；搭建监控：请求量、延迟、错误率、模型指标；模型上线前必须过 shadow mode 对比线上 baseline"],
                    ["Shadow mode 验证线上效果；A/B 测试确认业务指标提升；建立数据回流机制持续优化模型；推理服务必须有降级策略"],
                ],
            },
        },
    },
    {
        "file": "security-architect.md",
        "agent": {
            "name": "安全架构师",
            "description": "资深安全架构师，专精威胁建模、安全设计（secure-by-design）架构、信任边界分析、纵深防御，以及面向 Web、API、云原生和分布式系统的基于风险的安全评审。",
            "role_name": "安全架构师",
            "role_key": "security_architect",
            "department": "研发部",
            "team": "安全架构组",
            "employee_no": "SD-015",
        },
        "sop": {
            "skill_id": "security_architect_sop",
            "name": "安全架构评审流程",
            "business_domain": "security",
            "trigger_intents": ["安全架构", "威胁建模", "安全评审", "安全设计", "加固方案", "安全合规"],
            "bind": ["tech_knowledge"],
            # 无「工作流程」章节，显式定义
            "workflow": {
                "steps": ["收集系统上下文与资产清单", "威胁建模与攻击面分析", "安全设计评审与漏洞评估", "交付安全架构建议与加固方案"],
                "details": [
                    ["确认系统架构、技术栈、部署形态、数据流与信任边界；识别资产、用户角色与权限模型；确认合规要求（等保/ISO/行业规范）"],
                    ["用对抗式思维追问：什么会被滥用、失效时会发生什么、谁会从攻破中获益、爆炸半径多大；按 STRIDE 或 OWASP Top 10 识别威胁并排出优先级"],
                    ["评审身份认证（OAuth 2.0+PKCE/WebAuthn/MFA）、授权模型（RBAC/ABAC/ReBAC）、密钥管理、加密方案（TLS 1.3/AES-256-GCM）、输入校验与输出编码；识别漏洞按 CVSS 3.1+ 分级"],
                    ["输出威胁模型文档、风险清单（含严重性评级、可利用性证明、具体修复方案）与零信任/纵深防御加固建议；每条发现必须附带具体修复路径"],
                ],
            },
        },
    },
    {
        "file": "security-penetration-tester.md",
        "agent": {
            "name": "渗透测试工程师",
            "description": "专业渗透测试员，擅长侦察与攻击面测绘、漏洞利用与权限提升、Web 应用与 API 测试、云与基础设施评估，产出可溯源的攻击链证据。",
            "role_name": "渗透测试工程师",
            "role_key": "penetration_tester",
            "department": "测试部",
            "team": "安全测试组",
            "employee_no": "SD-016",
        },
        "sop": {
            "skill_id": "penetration_test_sop",
            "name": "渗透测试流程",
            "business_domain": "security",
            "trigger_intents": ["渗透测试", "安全测试", "漏洞扫描", "攻击面评估", "红队测试"],
            "bind": ["tech_knowledge", "test_standards"],
            # 无「工作流程」章节，显式定义
            "workflow": {
                "steps": ["确认授权范围与测试边界", "侦察与攻击面测绘", "漏洞利用与权限提升验证", "交付渗透测试报告"],
                "details": [
                    ["确认测试目标、授权范围、时间窗口与禁止操作（不破坏生产数据、不触发真实业务影响）；确认测试方法和标准（OWASP/PTES）"],
                    ["枚举对外可见资产：子域名、开放端口、暴露服务、泄露凭据、云存储错误配置；开展 OSINT；识别信任关系与横向移动路径"],
                    ["按方法论测试 Web/API（注入、XSS、CSRF、SSRF、IDOR、认证授权缺陷）、云配置与容器安全；串连低危发现为高影响攻击链，演示真实影响但控制在授权范围内"],
                    ["输出渗透测试报告：每个发现附完整攻击链（从初始访问到业务影响）、严重性评级（CVSS 3.1+）、复现步骤与修复建议；不公开敏感细节"],
                ],
            },
        },
    },
    {
        "file": "engineering-frontend-developer.md",
        "agent": {
            "name": "前端开发工程师",
            "description": "专业前端开发工程师，专注现代 Web 应用构建、React 组件开发、性能优化与无障碍设计，产出高质量、可扩展的前端实现。",
            "role_name": "前端开发工程师",
            "role_key": "frontend_developer",
            "department": "研发部",
            "team": "前端组",
            "employee_no": "SD-017",
        },
        "sop": {
            "skill_id": "frontend_dev_sop",
            "name": "前端开发流程",
            "business_domain": "frontend",
            "trigger_intents": ["前端开发", "React 组件", "页面实现", "UI 实现", "前端优化"],
            "bind": ["tech_knowledge"],
            # 角色文件有「你的工作流程」章节，显式覆盖以获得更干净的节点名
            "workflow": {
                "steps": ["项目搭建与架构", "组件开发", "性能优化", "测试与质量保证"],
                "details": [
                    ["使用适当的工具搭建现代开发环境；配置构建优化和性能监控；建立测试框架和 CI/CD 集成；创建组件架构和设计系统基础"],
                    ["创建带有适当 TypeScript 类型的可复用组件库；使用移动优先方法实现响应式设计；从一开始就将无障碍性构建到组件中"],
                    ["实施代码拆分和懒加载策略；优化图片和资源以适应 Web 交付；监控 Core Web Vitals（LCP < 2.5s, FID < 100ms, CLS < 0.1）并相应优化；设置性能预算和监控"],
                    ["编写全面的单元测试和集成测试；使用真实辅助技术进行无障碍测试；测试跨浏览器兼容性和响应式行为；为关键用户流程实施端到端测试"],
                ],
            },
        },
    },
    {
        "file": "engineering-database-optimizer.md",
        "agent": {
            "name": "数据库优化工程师",
            "description": "数据库性能专家，专注于 Schema 设计、查询优化、索引策略和性能调优，精通 PostgreSQL、MySQL 及 Supabase、PlanetScale 等现代数据库。",
            "role_name": "数据库优化工程师",
            "role_key": "database_optimizer",
            "department": "研发部",
            "team": "平台工程组",
            "employee_no": "SD-018",
        },
        "sop": {
            "skill_id": "database_optimize_sop",
            "name": "数据库优化流程",
            "business_domain": "database",
            "trigger_intents": ["数据库优化", "慢查询", "索引优化", "Schema 设计", "查询优化"],
            "bind": ["tech_knowledge"],
            # 无「工作流程」章节，显式定义
            "workflow": {
                "steps": ["收集慢查询与 Schema 上下文", "诊断查询计划与瓶颈", "制定索引与 Schema 优化方案", "交付优化结果与迁移建议"],
                "details": [
                    ["收集慢查询日志、EXPLAIN ANALYZE 输出、当前 Schema 结构、表数据量与增长趋势；确认业务查询模式（读多写多/高频热点）"],
                    ["解读查询计划定位瓶颈：全表扫描、缺失索引、N+1 查询、连接顺序、锁竞争；用 EXPLAIN ANALYZE 验证假设"],
                    ["设计索引策略（B-tree/GiST/GIN/部分索引/复合索引覆盖过滤+排序）；必要时做 Schema 规范化与反规范化权衡；外键必须有索引"],
                    ["输出优化清单（每个优化点带预期收益）、可回滚的迁移方案（零停机部署）、验证脚本；慢查询优化后复测确认"],
                ],
            },
        },
    },
    {
        "file": "product-manager.md",
        "agent": {
            "name": "产品经理",
            "description": "全局型产品负责人，掌控产品全生命周期——从需求发现、战略规划到路线图制定、干系人对齐、GTM 落地与结果度量。在商业目标、用户需求与技术现实之间架起桥梁。",
            "role_name": "产品经理",
            "role_key": "product_manager",
            "department": "产品部",
            "team": "产品组",
            "employee_no": "SD-019",
        },
        "sop": {
            "skill_id": "product_manage_sop",
            "name": "产品管理流程",
            "business_domain": "product",
            "trigger_intents": ["产品规划", "需求分析", "PRD", "路线图", "产品方案", "需求评审"],
            "bind": ["tech_knowledge", "success_cases"],
            # 无「工作流程」章节，显式定义
            "workflow": {
                "steps": ["需求发现与问题定义", "方案设计与 PRD 撰写", "干系人对齐与路线图排期", "交付与度量迭代"],
                "details": [
                    ["先找问题不要先跳方案：识别底层用户痛点或业务目标，至少追问三次为什么；用用户访谈/行为数据/客服信号/竞争压力验证需求假设；确认成功指标"],
                    ["先写新闻稿再写 PRD：用一段话说明用户为什么在意；PRD 含问题陈述、目标与成功指标、Non-Goals、用户画像与故事、方案概述、技术考量、发布计划"],
                    ["路线图每项必须有负责人、成功指标和时间范围；与工程/设计/销售/支持对齐，明确取舍；记录变更请求对照 Sprint 目标接受/延后/拒绝"],
                    ["交付 PRD 与路线图并持续沟通进度（意外就是失败，过度沟通）；上线之后必度量：跟踪指标验证假设，形成反馈闭环"],
                ],
            },
        },
    },
]

# 知识库业务键 -> 绑定 resource_type 键（org_bindings.json 中使用的前缀）
KB_BIND_KEYS = {
    "tech_knowledge": "技术知识库",
    "test_standards": "测试规范与验收标准",
    "success_cases": "成功案例库",
}


# ---------------------------------------------------------------------------
# Markdown 解析
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> dict:
    """提取 --- --- 之间的 YAML 前段（仅取 name/description/emoji 简单键值）。"""
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    meta: dict[str, str] = {}
    if not m:
        return meta
    for line in m.group(1).splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k in ("name", "description", "emoji"):
                meta[k] = v
    return meta


def extract_section(text: str, heading_pattern: str) -> str:
    """提取从匹配 heading 的章节开始，到下一个同级/更高章节之前的内容。"""
    lines = text.splitlines()
    start = None
    level = None
    for i, line in enumerate(lines):
        m = re.match(r"^(#{2,4})\s+(.*)", line)
        if m and re.search(heading_pattern, m.group(2)):
            start = i
            level = len(m.group(1))
            break
    if start is None:
        return ""
    out: list[str] = []
    in_code = False
    for line in lines[start + 1 :]:
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = re.match(r"^(#{1,4})\s+", line)
        if m and len(m.group(1)) <= level:
            break
        out.append(line)
    return "\n".join(out).strip()


def extract_list_items(section: str) -> list[str]:
    """提取章节中的列表项（- 或 1. 开头），去重保序。"""
    items: list[str] = []
    for line in section.splitlines():
        line = line.strip()
        m = re.match(r"^(?:[-*]|\d+[.、])\s+(.*)", line)
        if m:
            item = m.group(1).strip()
            # 跳过纯代码块内容
            if item.startswith("```") or item.startswith("#"):
                continue
            if item and item not in items:
                items.append(item)
    return items


def extract_subheadings(section: str) -> list[str]:
    """提取章节内 ### 子标题。"""
    return [
        re.sub(r"^[#\s]+", "", line).strip()
        for line in section.splitlines()
        if re.match(r"^###\s+", line.strip())
    ]


def build_persona_prompt(meta: dict, text: str) -> str:
    """将身份/使命/规则拼装为 persona_prompt。"""
    identity = extract_section(text, r"身份与记忆")
    mission = extract_section(text, r"核心使命")
    rules = extract_section(text, r"关键规则|必须遵守|必须遵循")

    parts: list[str] = []
    if meta.get("description"):
        parts.append(f"你是{meta['name']}。{meta['description']}")

    id_lines = extract_list_items(identity)
    if id_lines:
        parts.append("【身份与经验】\n" + "\n".join(f"- {x}" for x in id_lines[:8]))

    mission_items = extract_list_items(mission)
    mission_heads = extract_subheadings(mission)
    if mission_items:
        parts.append("【核心使命】\n" + "\n".join(f"- {x}" for x in mission_items[:12]))
    elif mission_heads:
        parts.append("【核心使命】\n" + "\n".join(f"- {x}" for x in mission_heads[:8]))

    rule_items = extract_list_items(rules)
    rule_heads = extract_subheadings(rules)
    if rule_items:
        parts.append("【关键规则】\n" + "\n".join(f"- {x}" for x in rule_items[:10]))
    elif rule_heads:
        parts.append("【关键规则】\n" + "\n".join(f"- {x}" for x in rule_heads[:8]))

    parts.append(
        "工作原则：先澄清需求与上下文，再按专业流程推进；输出结构化、可操作、可量化的结论；"
        "超出职责边界或信息不足时明确说明并建议转交对应同事；不编造事实，不确定的标注为假设。"
    )
    return "\n\n".join(parts)


def build_skill_card(agent_cfg: dict, sop_cfg: dict, text: str) -> dict:
    """将工作流程步骤转化为 SOP SkillCard（线性状态机）。"""
    workflow_cfg = sop_cfg.get("workflow")
    if workflow_cfg:
        steps = list(workflow_cfg["steps"])
        step_items = list(workflow_cfg["details"])
    else:
        workflow = extract_section(text, r"工作流程")
        steps = extract_subheadings(workflow)
        if not steps:
            steps = ["收集需求与上下文", "分析并制定方案", "执行并产出结果", "交付与复盘"]

        step_items: list[list[str]] = []
        lines = workflow.splitlines()
        cur: list[str] = []
        in_step = False
        for line in lines:
            if re.match(r"^###\s+", line.strip()):
                if in_step:
                    step_items.append(cur)
                cur = []
                in_step = True
            elif in_step and line.strip():
                cur.append(line.strip())
        if in_step:
            step_items.append(cur)

    nodes: list[dict] = []
    edges: list[dict] = []
    n = len(steps)
    for i, step in enumerate(steps):
        node_id = f"step_{i + 1}"
        details = step_items[i] if i < len(step_items) else []
        # 提炼指令：把列表项合成 instruction 的一段
        detail_text = "；".join(
            re.sub(r"^(?:[-*]|\d+[.、])\s+", "", d) for d in details[:6]
        )
        allowed: list[str] = ["ask_user", "continue_flow"]
        if i == 0:
            allowed = ["ask_clarification", "continue_flow"]
        if i == n - 1:
            allowed = ["answer_user", "handoff_human", "continue_flow"]

        node = {
            "node_id": node_id,
            "type": "collect_info",
            "name": step,
            "instruction": (
                f"将本步骤作为目标而不是固定话术：{step}。"
                + (f"参考要点：{detail_text}。" if detail_text else "")
                + "已满足的信息不再重复追问，缺失信息优先从已有上下文提取，仍缺失时仅追问缺失项。"
            ),
            "expected_user_info": [],
            "allowed_actions": allowed,
        }
        nodes.append(node)
        if i > 0:
            edges.append(
                {
                    "source_node_id": f"step_{i}",
                    "next_node_id": node_id,
                    "condition": None,
                    "priority": 0,
                    "label": None,
                }
            )

    return {
        "skill_id": sop_cfg["skill_id"],
        "name": sop_cfg["name"],
        "version": "1.0.0",
        "business_domain": sop_cfg["business_domain"],
        "description": f"{agent_cfg['name']}的标准工作流程：{' → '.join(steps)}。",
        "trigger_intents": sop_cfg["trigger_intents"],
        "user_utterance_examples": [f"帮我{sop_cfg['trigger_intents'][0]}", f"我要{sop_cfg['trigger_intents'][1]}"],
        "goal": steps,
        "required_info": [],
        "slot_filling_policy": {
            "enabled": True,
            "multi_slot_per_turn": True,
            "extract_scope": "all_skill_expected_user_info",
            "skip_satisfied_steps": True,
            "description": "每轮同时抽取用户已表达的信息，已满足的信息不再追问。",
            "target_info": [],
        },
        "response_rules": [
            "输出结构化结果，关键结论带依据或数据。",
            "信息不足时先追问，不要臆测。",
            "超出职责边界的情况转人工并附上已收集的上下文。",
        ],
        "nodes": nodes,
        "edges": edges,
        "start_node_id": "step_1",
        "terminal_node_ids": [f"step_{n}"],
        "interruption_policy": {
            "related_question": "可以临时回答，回答后回到当前流程。",
            "unrelated_business": "可以切换到新技能，并保存当前流程进度。",
            "chitchat": "简短回应后，引导用户继续当前流程。",
            "user_wants_human": "直接转人工。",
        },
    }


def build_agent(agent_cfg: dict, meta: dict, persona: str) -> dict:
    return {
        "name": agent_cfg["name"],
        "description": agent_cfg["description"],
        "persona_prompt": persona,
        "is_overall": False,
        "source_mode": "blank",
        "metadata": {
            "role_name": agent_cfg["role_name"],
            "role_key": agent_cfg["role_key"],
            "department": agent_cfg["department"],
            "team": agent_cfg["team"],
            "employee_no": agent_cfg["employee_no"],
            "work_styles": ["结构化输出", "专业审慎", "先澄清后执行"],
            "expertise_tags": [agent_cfg["role_name"], "质量意识", "技术文档"],
            "work_modes": ["chat"],
            "avatar_kind": "preset",
            "avatar_preset": meta.get("emoji", "🤖"),
        },
    }


def build_bindings(agent_name: str, sop_cfg: dict) -> list[dict]:
    bindings = [
        {
            "resource_type": "skill",
            "resource_id": sop_cfg["skill_id"],
            "status": "active",
            "metadata": {},
        }
    ]
    for kb_key in sop_cfg.get("bind", []):
        if kb_key in KB_BIND_KEYS:
            bindings.append(
                {
                    "resource_type": "knowledge_base",
                    "resource_id": KB_BIND_KEYS[kb_key],
                    "status": "active",
                    "metadata": {},
                }
            )
    return [{"agent_name": agent_name, "bindings": bindings}]


def main() -> int:
    role_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/tmp/opencode/agency_roles")
    out_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).resolve().parent

    agents: list[dict] = []
    skills: list[dict] = []
    bindings: list[dict] = []

    for cfg in ROLE_MAP:
        path = role_dir / cfg["file"]
        if not path.exists():
            print(f"[warn] 缺少角色文件: {path}")
            continue
        text = path.read_text(encoding="utf-8")
        meta = parse_frontmatter(text)
        agent_cfg = cfg["agent"]
        sop_cfg = cfg["sop"]

        persona = build_persona_prompt(meta, text)
        agents.append(build_agent(agent_cfg, meta, persona))
        skills.append({"tenant_id": "__TENANT__", "content": build_skill_card(agent_cfg, sop_cfg, text), "status": "published"})
        bindings.extend(build_bindings(agent_cfg["name"], sop_cfg))
        print(f"[ok] {agent_cfg['name']} ({agent_cfg['employee_no']}) <- {cfg['file']}")

    (out_dir / "org_agents_new.json").write_text(
        json.dumps(agents, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "org_skills_new.json").write_text(
        json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "org_bindings_new.json").write_text(
        json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n完成：{len(agents)} 员工 / {len(skills)} SOP / {len(bindings)} 绑定")
    print(f"输出: {out_dir}/org_agents_new.json, org_skills_new.json, org_bindings_new.json")
    return 0


if __name__ == "__main__":
    sys.exit(main())
