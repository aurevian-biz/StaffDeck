#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
merge_skills_tools.py
将 A/B 组通用技能（org_general_skills_new.json）与 C 组工具（org_tools_new.json）
并入主配置，并更新员工绑定（org_bindings.json）。

用法: python3 it-org/merge_skills_tools.py
"""
from __future__ import annotations

import json
from pathlib import Path

BASE = Path("it-org")

# ---------------------------------------------------------------- 绑定映射

# 通用技能 slug → 应绑定的员工名列表
GENERAL_SKILL_BINDINGS: dict[str, list[str]] = {
    # A 组
    "ce-brainstorm": ["产品经理"],
    "ce-plan": ["产品经理", "方案架构师"],
    "ce-ideate": ["产品经理"],
    "ce-debug": ["软件工程师", "售后支持工程师"],
    "ce-code-review": ["代码审查专家"],
    "ce-simplify-code": ["软件工程师"],
    "ce-doc-review": ["方案架构师", "产品经理"],
    "ce-strategy": ["产品经理"],
    "ce-agent-native-architecture": ["方案架构师", "AI 应用工程师"],
    "ce-agent-native-audit": ["安全架构师"],
    "ce-dhh-rails-style": ["软件工程师"],
    "reviewing-openspec-artifacts": ["测试验收专员"],
    # B 组
    "ce-commit": ["软件工程师"],
    "ce-commit-push-pr": ["软件工程师"],
    "ce-clean-gone-branches": ["DevOps 自动化工程师"],
    "ce-worktree": ["软件工程师", "DevOps 自动化工程师"],
    "ce-compound": ["知识运营专员"],
    "ce-compound-refresh": ["知识运营专员"],
    "ce-release-notes": ["产品经理"],
    "ce-setup": ["DevOps 自动化工程师"],
    "ce-riffrec-feedback-analysis": ["售后支持工程师", "知识运营专员"],
    "ce-optimize": ["AI 应用工程师"],
}

# C 组工具 name → 应绑定的员工名列表
TOOL_BINDINGS: dict[str, list[str]] = {
    "image.generate.gemini": ["前端开发工程师", "AI 应用工程师"],
    "proof.doc.review": ["产品经理", "方案架构师"],
    "product.pulse": ["产品经理"],
    "search.web.last30": ["售前咨询顾问", "产品经理"],
    "trend.analyze": ["产品经理"],
    "slack.search": ["产品经理", "知识运营专员"],
    "browser.automate": ["测试验收专员", "前端开发工程师"],
    "agent.browser.cli": ["测试验收专员"],
    "ast.search": ["软件工程师"],
}


def load(name: str):
    return json.loads((BASE / name).read_text(encoding="utf-8"))


def save(name: str, data) -> None:
    (BASE / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    # 1. 合并通用技能
    main_skills = load("org_general_skills.json")
    new_skills = load("org_general_skills_new.json")
    existing_slugs = {s["slug"] for s in main_skills}
    added = 0
    for sk in new_skills:
        if sk["slug"] in existing_slugs:
            print(f"[skip] 通用技能已存在: {sk['slug']}")
            continue
        main_skills.append(sk)
        existing_slugs.add(sk["slug"])
        added += 1
    save("org_general_skills.json", main_skills)
    print(f"通用技能: 原有 {len(main_skills) - added} + 新增 {added} = {len(main_skills)}")

    # 2. 合并工具
    main_tools = load("org_tools.json")
    new_tools = load("org_tools_new.json")
    existing_tool_names = {t["name"] for t in main_tools}
    added_tools = 0
    for t in new_tools:
        if t["name"] in existing_tool_names:
            print(f"[skip] 工具已存在: {t['name']}")
            continue
        main_tools.append(t)
        existing_tool_names.add(t["name"])
        added_tools += 1
    save("org_tools.json", main_tools)
    print(f"工具: 原有 {len(main_tools) - added_tools} + 新增 {added_tools} = {len(main_tools)}")

    # 3. 更新绑定
    bindings = load("org_bindings.json")  # dict: 员工名 → [{resource_type, resource_id, status}]
    assert isinstance(bindings, dict), "org_bindings.json 应为 dict（员工名→绑定数组）"

    # 校验员工名存在
    agents = {a["name"] for a in load("org_agents.json")}

    def ensure_agent(agent_name: str) -> list:
        if agent_name not in agents:
            raise KeyError(f"绑定目标员工不存在于 org_agents.json: {agent_name}")
        return bindings.setdefault(agent_name, [])

    def add_binding(agent_name: str, rtype: str, rid: str) -> None:
        arr = ensure_agent(agent_name)
        if not any(b["resource_type"] == rtype and b["resource_id"] == rid for b in arr):
            arr.append({"resource_type": rtype, "resource_id": rid, "status": "active"})

    gs_added = tool_added = 0
    for slug, agent_names in GENERAL_SKILL_BINDINGS.items():
        for an in agent_names:
            add_binding(an, "general_skill", slug)
            gs_added += 1
    for tname, agent_names in TOOL_BINDINGS.items():
        for an in agent_names:
            add_binding(an, "tool", tname)
            tool_added += 1
    save("org_bindings.json", bindings)
    print(f"绑定: 新增 general_skill {gs_added} 条 + tool {tool_added} 条，共 {sum(len(v) for v in bindings.values())} 条（{len(bindings)} 个员工）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
