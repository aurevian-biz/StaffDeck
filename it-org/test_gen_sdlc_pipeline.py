#!/usr/bin/env python3
"""gen_sdlc_pipeline 生成器的测试（RED→GREEN→SURFACE）。

场景契约：
- S1 happy: 默认参数生成 → YAML 可解析、25 steps、字段完整（id/role/task/output/depends_on）、inputs 默认值正确
- S2 edge: --include-ai false 等参数 → inputs 默认值正确反映；--out 自定义路径生效；--skip-discovery true 跳过发现阶段
- S3 regression: 生成的默认 YAML 与现有 sdlc_pipeline.yaml 步骤 id 集合/顺序/依赖一致
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
IT_ORG = Path(__file__).resolve().parent
GEN = IT_ORG / "gen_sdlc_pipeline.py"
EXISTING = IT_ORG / "sdlc_pipeline.yaml"
ORCHESTRATOR = IT_ORG / "staffdeck_orchestrator.py"

sys.path.insert(0, str(IT_ORG))


# ---------------------------------------------------------------- S1 happy path

def test_s1_default_generates_parseable_yaml_with_25_steps(tmp_path):
    """默认参数 → YAML 可解析、25 steps、关键字段完整。"""
    out = tmp_path / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out)],
        check=True, capture_output=True, text=True,
    )
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert data["name"] == "sdlc-opencode-pipeline"
    steps = data["steps"]
    assert len(steps) == 25, f"应生成 25 个步骤，实际 {len(steps)}"
    ids = [s["id"] for s in steps]
    assert len(ids) == len(set(ids)), "步骤 id 必须唯一"
    for s in steps:
        assert "id" in s, f"{s} 缺少 id"
        if s.get("type") not in ("approval", "human_input"):
            assert "role" in s, f"{s['id']} 缺少 role"
            assert "task" in s, f"{s['id']} 缺少 task"
            assert "output" in s, f"{s['id']} 缺少 output"
        else:
            assert "prompt" in s, f"{s['id']} 缺少 prompt"


def test_s1_default_inputs_match_expected():
    """默认 inputs 值正确（project_name 等）。"""
    data = _gen_to_dict()
    inputs = {i["name"]: i.get("default") for i in data["inputs"]}
    assert inputs["project_name"] == "智能客服Agent系统"
    assert inputs["requirements"].startswith("构建企业客服智能体")
    assert inputs["include_ai"] == "true"
    assert inputs["include_perf"] == "false"
    assert inputs["external_release"] == "true"
    assert inputs["skip_discovery"] == "false"


def test_s1_opencode_steps_present():
    """OpenCode 融合步骤必须存在。"""
    data = _gen_to_dict()
    ids = [s["id"] for s in data["steps"]]
    opencode_steps = [
        "discovery_ideate", "discovery_strategy", "discovery_brainstorm",
        "openspec_proposal", "openspec_design", "implementation_plan",
        "commit_push_pr", "knowledge_compound",
    ]
    for step in opencode_steps:
        assert step in ids, f"缺少 OpenCode 融合步骤: {step}"


# ---------------------------------------------------------------- S2 edge cases

def test_s2_cli_inputs_override_defaults(tmp_path):
    """--project-name / --requirements 覆盖 inputs 默认值。"""
    out = tmp_path / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out),
         "--project-name", "订单系统", "--requirements", "处理订单"],
        check=True, capture_output=True, text=True,
    )
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    inputs = {i["name"]: i.get("default") for i in data["inputs"]}
    assert inputs["project_name"] == "订单系统"
    assert inputs["requirements"] == "处理订单"
    # 步骤 task 保留模板引用（运行时由编排器解析），断言模板存在
    prd_step = next(s for s in data["steps"] if s["id"] == "product_prd")
    assert "{{project_name}}" in prd_step["task"]


def test_s2_generated_yaml_loads_by_orchestrator(tmp_path):
    """生成的 YAML 能被编排器 --dry-run 解析，且分层内容完整（L1~L17）。"""
    out = tmp_path / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out)],
        check=True, capture_output=True, text=True,
    )
    r = subprocess.run(
        [sys.executable, str(ORCHESTRATOR), str(out), "--dry-run"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"编排器 dry-run 失败: {r.stderr[-2000:]}"
    # 关键步骤在输出中出现
    expected_steps = [
        "discovery_ideate", "product_prd", "openspec_proposal",
        "solution_architect", "openspec_design", "architecture_approval",
        "implementation_plan", "software_dev", "code_review",
        "api_test", "release_approval", "commit_push_pr",
        "delivery_summary", "knowledge_compound", "knowledge_sediment",
    ]
    for step in expected_steps:
        assert step in r.stdout, f"dry-run 输出中缺少步骤: {step}"


def test_s2_boolean_switches_change_inputs(tmp_path):
    """--no-include-ai / --include-perf / --no-external-release 反映到 inputs 默认值。"""
    out = tmp_path / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out),
         "--no-include-ai", "--include-perf", "--no-external-release"],
        check=True, capture_output=True, text=True,
    )
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    inputs = {i["name"]: i.get("default") for i in data["inputs"]}
    assert inputs["include_ai"] == "false"
    assert inputs["include_perf"] == "true"
    assert inputs["external_release"] == "false"


def test_s2_skip_discovery_changes_input(tmp_path):
    """--skip-discovery 反映到 inputs 默认值。"""
    out = tmp_path / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out), "--skip-discovery"],
        check=True, capture_output=True, text=True,
    )
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    inputs = {i["name"]: i.get("default") for i in data["inputs"]}
    assert inputs["skip_discovery"] == "true"


def test_s2_out_to_nonexistent_dir_creates_parent(tmp_path):
    """--out 指向不存在的目录时应自动创建父目录（回归 Oracle 缺陷 1）。"""
    out = tmp_path / "deep" / "nested" / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out)],
        check=True, capture_output=True, text=True,
    )
    assert out.exists(), "应自动创建父目录并写出文件"
    data = yaml.safe_load(out.read_text(encoding="utf-8"))
    assert len(data["steps"]) == 25


def test_s2_block_scalar_and_flow_style_format(tmp_path):
    """生成文件格式对齐现有文件：task 为块标量、depends_on 为 flow 风格。"""
    out = tmp_path / "pipeline.yaml"
    subprocess.run(
        [sys.executable, str(GEN), "--out", str(out)],
        check=True, capture_output=True, text=True,
    )
    text = out.read_text(encoding="utf-8")
    prd_block = re.search(r"task: \|-\n", text)
    assert prd_block, "多行 task 应为块标量 |-"
    assert "depends_on: [product_prd]" in text or "depends_on: [openspec_proposal]" in text, \
        "depends_on 应为 flow 风格 [a, b]"
    assert "# 项目名称" in text, "inputs comment 应注入到生成文件"


# ---------------------------------------------------------------- S3 regression

def test_s3_generated_steps_match_existing_file():
    """生成的默认 YAML 与现有 sdlc_pipeline.yaml 步骤 id 集合/顺序/全字段一致。"""
    generated = _gen_to_dict()
    existing = yaml.safe_load(EXISTING.read_text(encoding="utf-8"))
    g_steps = {s["id"]: s for s in generated["steps"]}
    e_steps = {s["id"]: s for s in existing["steps"]}
    assert set(g_steps) == set(e_steps), (
        f"步骤 id 集合不一致\n新增: {set(g_steps) - set(e_steps)}\n缺失: {set(e_steps) - set(g_steps)}"
    )
    for sid in e_steps:
        g, e = g_steps[sid], e_steps[sid]
        for field in ("role", "depends_on", "condition", "type",
                      "task", "output", "max_turns", "prompt"):
            assert g.get(field) == e.get(field), f"{sid} {field} 不一致"


# ---------------------------------------------------------------- 辅助

def _gen_to_dict() -> dict:
    out = IT_ORG / ".tmp_gen_pipeline.yaml"
    try:
        subprocess.run(
            [sys.executable, str(GEN), "--out", str(out)],
            check=True, capture_output=True, text=True,
        )
        return yaml.safe_load(out.read_text(encoding="utf-8"))
    finally:
        if out.exists():
            out.unlink()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
