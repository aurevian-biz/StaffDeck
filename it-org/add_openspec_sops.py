#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 OpenSpec 规范驱动开发流程固化为 StaffDeck SOP，并入主配置。
方式①：openspec_propose_sop（产品经理）+ openspec_design_sop（方案架构师）
用法：python3 it-org/add_openspec_sops.py
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent

BASE_INTERRUPTION = {
    "related_question": "可以临时回答，回答后回到当前流程。",
    "unrelated_business": "可以切换到新技能，并保存当前流程进度。",
    "chitchat": "简短回应后，引导用户继续当前流程。",
    "user_wants_human": "直接转人工。",
}

PROPOSE_SOP = {
    "skill_id": "openspec_propose_sop",
    "name": "OpenSpec 规范提案流程",
    "version": "1.0.0",
    "business_domain": "product",
    "description": "规范驱动开发（SDD）的变更提案流程：需求收集与场景化 → 撰写 proposal.md（Requirement 带 WHEN/THEN 场景）→ 干系人评审门禁。",
    "trigger_intents": ["规范提案", "openspec", "变更提案", "proposal", "需求规格", "场景化需求"],
    "user_utterance_examples": [
        "把客户需求写成规范提案",
        "按 OpenSpec 流程走变更提案",
        "这个需求怎么场景化"
    ],
    "goal": [
        "收集需求上下文与成功指标",
        "将需求拆解为可验证的 WHEN/THEN 场景",
        "撰写 proposal.md（含 SHALL/SHOULD/MAY 措辞的 Requirement）",
        "干系人评审确认后交接",
    ],
    "required_info": ["problem_statement", "target_users", "success_metrics"],
    "slot_filling_policy": {
        "enabled": True,
        "multi_slot_per_turn": True,
        "extract_scope": "all_skill_expected_user_info",
        "skip_satisfied_steps": True,
        "description": "每轮同时抽取问题陈述、目标用户、成功指标、约束与边界等信息，已满足的信息不再追问。",
        "target_info": ["problem_statement", "target_users", "success_metrics", "constraints"],
    },
    "response_rules": [
        "先找问题不要先跳方案：识别底层痛点或业务目标，至少追问三次为什么。",
        "每个 Requirement 必须带可验证的 Scenario（WHEN...THEN...），不可验证的需求不写入提案。",
        "规范动词必须准确：SHALL=必须满足、SHOULD=应当满足、MAY=可以满足，不得混用。",
        "提案必须包含 Non-Goals，明确本次变更不做的事。",
        "成功指标必须可度量，不能使用模糊表述。",
        "需求存在冲突或超出平台能力时转人工并附上已收集的上下文。",
    ],
    "nodes": [
        {
            "node_id": "collect_context",
            "name": "收集需求上下文",
            "instruction": "将本步骤作为目标而不是固定话术：识别需求来源（客户/内部/竞品/数据信号），澄清问题陈述、目标用户、成功指标与约束边界。参考要点：先找问题不要先跳方案，至少追问三次为什么；用数据或案例验证需求假设。已满足的信息不再重复追问，仍缺失时仅追问缺失项。",
            "expected_user_info": ["problem_statement", "target_users", "success_metrics", "constraints"],
            "allowed_actions": ["ask_clarification", "continue_flow"],
        },
        {
            "node_id": "scenario_breakdown",
            "name": "需求场景化拆解",
            "instruction": "将本步骤作为目标而不是固定话术：把需求拆解为可验证的 WHEN/THEN 场景列表，每个场景包含前置条件、触发动作、预期结果；参考成功案例库中的既有规范样例。参考要点：场景粒度要可被测试验收直接映射；识别边界场景与异常路径。已满足的信息不再重复追问，仍缺失时仅追问缺失项。",
            "expected_user_info": ["scenarios"],
            "allowed_actions": ["knowledge_query", "ask_user", "continue_flow"],
            "knowledge_scope": {"buckets": ["success_cases"]},
        },
        {
            "node_id": "write_proposal",
            "name": "撰写 proposal.md",
            "instruction": "将本步骤作为目标而不是固定话术：产出 OpenSpec 规范的 proposal.md，结构含：问题陈述、目标与成功指标、需求规格（每条 Requirement 用 SHALL/SHOULD/MAY 措辞并带 Scenario WHEN/THEN）、Non-Goals、变更影响范围。参考要点：每个需求都能被 WHEN/THEN 场景验证；不写实现细节（那是 design.md 的职责）。",
            "expected_user_info": [],
            "allowed_actions": ["answer_user", "continue_flow"],
        },
        {
            "node_id": "review_gate",
            "name": "干系人评审门禁",
            "instruction": "将本步骤作为目标而不是固定话术：把 proposal.md 交给干系人评审（人工确认），确认范围、优先级与可验证性；评审通过则输出最终提案交接给方案架构师，不通过则收集反馈修订后再评审。参考要点：记录变更请求并明确接受/延后/拒绝。",
            "expected_user_info": ["review_decision"],
            "allowed_actions": ["answer_user", "handoff_human", "continue_flow"],
        },
    ],
    "edges": [
        {"source_node_id": "collect_context", "next_node_id": "scenario_breakdown", "condition": None, "priority": 0, "label": "上下文完整"},
        {"source_node_id": "scenario_breakdown", "next_node_id": "write_proposal", "condition": None, "priority": 0, "label": "场景化完成"},
        {"source_node_id": "write_proposal", "next_node_id": "review_gate", "condition": None, "priority": 0, "label": "提案完成"},
    ],
    "start_node_id": "collect_context",
    "terminal_node_ids": ["review_gate"],
    "interruption_policy": BASE_INTERRUPTION,
}

DESIGN_SOP = {
    "skill_id": "openspec_design_sop",
    "name": "OpenSpec 设计实现流程",
    "version": "1.0.0",
    "business_domain": "delivery",
    "description": "规范驱动开发（SDD）的设计与实现流程：审阅 proposal 规范 → 设计技术方案 → 撰写 design.md 与 tasks.md → 设计评审门禁。",
    "trigger_intents": ["规范设计", "openspec 设计", "design.md", "设计任务拆解", "按规范实现"],
    "user_utterance_examples": [
        "根据提案写设计文档",
        "把规范转成开发任务",
        "按 OpenSpec 流程设计实现方案"
    ],
    "goal": [
        "审阅 proposal 与既有规范",
        "设计技术方案（架构/数据/接口）",
        "撰写 design.md 与 tasks.md",
        "设计评审门禁后交接编码",
    ],
    "required_info": ["proposal_content"],
    "slot_filling_policy": {
        "enabled": True,
        "multi_slot_per_turn": True,
        "extract_scope": "all_skill_expected_user_info",
        "skip_satisfied_steps": True,
        "description": "每轮抽取提案内容、技术约束、既有系统上下文等信息，已满足的信息不再追问。",
        "target_info": ["proposal_content", "tech_constraints"],
    },
    "response_rules": [
        "设计必须逐条响应 proposal 中的 Requirement，不能遗漏或跳过任何 SHALL 项。",
        "design.md 只描述怎么做（技术方案），不重写需求；需求变更需回到提案流程。",
        "tasks.md 的任务必须可独立验证，每个任务标注对应需求编号与验收标准。",
        "涉及平台能力（SOP/知识库/工具/通用技能）时引用技术知识库，不臆造不存在的功能。",
        "设计存在重大不确定性或需求歧义时转人工并附上提案上下文。",
    ],
    "nodes": [
        {
            "node_id": "review_proposal",
            "name": "审阅规范提案",
            "instruction": "将本步骤作为目标而不是固定话术：通读 proposal.md，逐条列出 Requirement（含 WHEN/THEN 场景）作为设计输入清单；识别技术约束与既有系统上下文。参考要点：需求不清晰或场景缺失时先返回产品经理澄清，不要自行脑补需求。",
            "expected_user_info": ["proposal_content", "tech_constraints"],
            "allowed_actions": ["knowledge_query", "ask_clarification", "continue_flow"],
            "knowledge_scope": {"buckets": ["tech_knowledge"]},
        },
        {
            "node_id": "design_solution",
            "name": "设计技术方案",
            "instruction": "将本步骤作为目标而不是固定话术：针对每条 Requirement 设计技术方案：总体架构、数据模型、接口契约、组件划分；智能体项目需明确员工/SOP/知识库/工具规划。参考要点：引用技术知识库中的架构模式与交付流程制度库中的标准；方案必须能覆盖所有 SHALL 场景。",
            "expected_user_info": [],
            "allowed_actions": ["knowledge_query", "ask_user", "continue_flow"],
            "knowledge_scope": {"buckets": ["tech_knowledge", "delivery_process"]},
        },
        {
            "node_id": "write_design_tasks",
            "name": "撰写 design.md 与 tasks.md",
            "instruction": "将本步骤作为目标而不是固定话术：产出 design.md（技术方案、数据模型、接口定义、风险与回退）与 tasks.md（按依赖排序的任务清单，每项含需求编号、验收标准、负责人建议）。参考要点：任务粒度适中可独立验证；明确阶段划分与里程碑。",
            "expected_user_info": [],
            "allowed_actions": ["answer_user", "continue_flow"],
        },
        {
            "node_id": "design_gate",
            "name": "设计评审门禁",
            "instruction": "将本步骤作为目标而不是固定话术：把 design.md 与 tasks.md 交给人工评审确认；评审通过则交接编码阶段（软件工程师/AI 应用工程师），不通过则收集意见修订。参考要点：评审重点=需求覆盖完整性、接口契约清晰度、任务可验收性。",
            "expected_user_info": ["design_decision"],
            "allowed_actions": ["answer_user", "handoff_human", "continue_flow"],
        },
    ],
    "edges": [
        {"source_node_id": "review_proposal", "next_node_id": "design_solution", "condition": None, "priority": 0, "label": "提案审阅完成"},
        {"source_node_id": "design_solution", "next_node_id": "write_design_tasks", "condition": None, "priority": 0, "label": "方案确定"},
        {"source_node_id": "write_design_tasks", "next_node_id": "design_gate", "condition": None, "priority": 0, "label": "文档完成"},
    ],
    "start_node_id": "review_proposal",
    "terminal_node_ids": ["design_gate"],
    "interruption_policy": BASE_INTERRUPTION,
}


def main() -> None:
    skills_path = ROOT / "org_skills.json"
    bindings_path = ROOT / "org_bindings.json"

    skills = json.loads(skills_path.read_text(encoding="utf-8"))
    existing_ids = {s["content"]["skill_id"] for s in skills}
    added = []
    for card in (PROPOSE_SOP, DESIGN_SOP):
        if card["skill_id"] in existing_ids:
            print(f"[skip] 技能已存在: {card['skill_id']}")
            continue
        skills.append({"tenant_id": None, "content": card, "status": "published"})
        added.append(card["skill_id"])
        print(f"[add] 技能: {card['skill_id']} ({card['name']})")
    skills_path.write_text(json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8")

    bindings = json.loads(bindings_path.read_text(encoding="utf-8"))
    new_bindings = {
        "产品经理": {"resource_type": "skill", "resource_id": "openspec_propose_sop", "status": "active"},
        "方案架构师": {"resource_type": "skill", "resource_id": "openspec_design_sop", "status": "active"},
    }
    for agent_name, binding in new_bindings.items():
        if agent_name not in bindings:
            print(f"[warn] 员工不存在，跳过绑定: {agent_name}")
            continue
        if any(b["resource_type"] == "skill" and b["resource_id"] == binding["resource_id"] for b in bindings[agent_name]):
            print(f"[skip] 绑定已存在: {agent_name} -> {binding['resource_id']}")
            continue
        bindings[agent_name].append(binding)
        print(f"[add] 绑定: {agent_name} -> {binding['resource_id']}")
    bindings_path.write_text(json.dumps(bindings, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n完成。新增 {len(added)} 个技能: {', '.join(added)}")


if __name__ == "__main__":
    sys.exit(main())
