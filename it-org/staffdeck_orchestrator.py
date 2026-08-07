#!/usr/bin/env python3
"""StaffDeck 数字员工流水线编排器（agency-orchestrator schema adapter）。

读取 AO 兼容的 YAML 工作流（如 sdlc_pipeline.yaml），把每个 step 派给
StaffDeck 数字员工执行：
  - 解析 YAML → 构建 DAG → 分层并行执行（concurrency 控制）
  - {{变量}} 步骤间传输出
  - condition 条件不满足则跳过
  - approval / human_input 人工节点暂停等输入
  - 失败指数退避重试（llm.retry）
  - 输出归档 ao-output/<name>-<时间戳>/{summary.md, steps/N-<id>.md, metadata.json}

依赖：pip install pyyaml requests
用法：
  python staffdeck_orchestrator.py sdlc_pipeline.yaml \
      --base-url http://127.0.0.1:5173 --username admin --password admin \
      --tenant-id tenant_demo --input project_name=xxx --dry-run --non-interactive
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any, Optional

try:
    import requests
except ImportError:
    sys.exit("缺少依赖：请先运行 pip install requests")

try:
    import yaml
except ImportError:
    sys.exit("缺少依赖：请先运行 pip install pyyaml")


# ---------------------------------------------------------------- 工具函数

VAR_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")

RESERVED_STEP_TYPES = {"approval", "human_input"}


def resolve_template(text: str, variables: dict[str, Any]) -> str:
    """把 {{var}} 替换为变量值。变量缺失时替换为空串。"""

    def _sub(match: re.Match) -> str:
        name = match.group(1)
        value = variables.get(name, "")
        return str(value) if value is not None else ""

    return VAR_RE.sub(_sub, text)


def eval_condition(condition: Optional[str], variables: dict[str, Any]) -> bool:
    """评估 AO 风格条件表达式。

    支持：{{x}} contains 文本 | {{x}} == 值 | {{x}} != 值 | 组合用 and / or
    例如： "{{include_ai}} == true and {{project_name}} contains 智能"
    """
    if not condition or not condition.strip():
        return True
    expr = resolve_template(condition, variables).strip()

    def _eval_single(token: str) -> bool:
        token = token.strip()
        for op in (" contains ", " == ", " != "):
            if op in token:
                left, right = token.split(op, 1)
                left, right = left.strip(), right.strip().strip("'\"")
                if op == " contains ":
                    return right.lower() in str(left).lower()
                if op == " == ":
                    return str(left).strip() == right
                return str(left).strip() != right
        # 裸布尔
        return token.lower() in ("true", "yes", "1")

    # 简单 and/or 拆解（不支持括号）
    if " and " in expr:
        return all(_eval_single(t) for t in expr.split(" and "))
    if " or " in expr:
        return any(_eval_single(t) for t in expr.split(" or "))
    return _eval_single(expr)


def sleep_backoff(attempt: int) -> None:
    time.sleep(min(2 ** attempt, 30))


# ---------------------------------------------------------------- StaffDeck 客户端

class StaffDeckClient:
    def __init__(self, base_url: str, username: str, password: str, tenant_id: str):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.token: Optional[str] = None
        self.session = requests.Session()
        self.session.verify = False
        self._agents_by_name: dict[str, str] = {}

        resp = self.session.post(
            f"{self.base_url}/api/auth/login",
            json={"tenant_id": tenant_id, "username": username, "password": password},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"登录失败 ({resp.status_code}): {resp.text[:300]}")
        self.token = resp.json().get("token")
        self.session.headers["Authorization"] = f"Bearer {self.token}"

    # ---- 员工解析 ----
    def agent_id(self, agent_name: str) -> str:
        if agent_name in self._agents_by_name:
            return self._agents_by_name[agent_name]
        resp = self.session.get(
            f"{self.base_url}/api/enterprise/agents",
            params={"tenant_id": self.tenant_id},
            timeout=30,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"获取员工列表失败 ({resp.status_code}): {resp.text[:300]}")
        for agent in resp.json():
            self._agents_by_name[agent["name"]] = agent["id"]
        if agent_name not in self._agents_by_name:
            raise RuntimeError(
                f"员工不存在: {agent_name}。请先运行 import_staffdeck.py 导入配置"
            )
        return self._agents_by_name[agent_name]

    # ---- 聊天 ----
    def create_session(self, agent_id: str, title: str) -> str:
        resp = self.session.post(
            f"{self.base_url}/api/chat/sessions",
            json={"tenant_id": self.tenant_id, "agent_id": agent_id, "title": title},
            timeout=30,
        )
        if resp.status_code not in (200, 201):
            raise RuntimeError(f"创建会话失败 ({resp.status_code}): {resp.text[:300]}")
        data = resp.json()
        # 兼容 ChatSessionRead(id) 与历史 session_id 字段
        return data.get("session_id") or data["id"]

    def turn(self, session_id: str, message: str, timeout: int = 300000) -> dict:
        """发一轮消息，同步返回 ChatTurnResponse。"""
        resp = self.session.post(
            f"{self.base_url}/api/chat/turn",
            json={
                "tenant_id": self.tenant_id,
                "session_id": session_id,
                "message": message,
                "channel": "web",
            },
            timeout=timeout,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"turn 失败 ({resp.status_code}): {resp.text[:500]}")
        return resp.json()

    def get_trace(self, session_id: str) -> list:
        resp = self.session.get(
            f"{self.base_url}/api/chat/sessions/{session_id}/trace",
            params={"tenant_id": self.tenant_id},
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        return resp.json() if isinstance(resp.json(), list) else [resp.json()]

    def get_messages(self, session_id: str) -> list:
        resp = self.session.get(
            f"{self.base_url}/api/chat/sessions/{session_id}/messages",
            params={"tenant_id": self.tenant_id},
            timeout=30,
        )
        if resp.status_code != 200:
            return []
        return resp.json()


# ---------------------------------------------------------------- 编排器

class Orchestrator:
    def __init__(self, workflow: dict, client: StaffDeckClient,
                 cli_inputs: dict[str, str], interactive: bool = True):
        self.workflow = workflow
        self.client = client
        self.steps = workflow["steps"]
        self.concurrency = int(workflow.get("concurrency", 2))
        self.retry = int(workflow.get("llm", {}).get("retry", 3))
        self.turn_timeout = int(workflow.get("llm", {}).get("timeout", 300000))
        self.interactive = interactive
        self.variables: dict[str, Any] = {}
        self._lock = Lock()
        self._step_results: dict[str, dict] = {}
        self._skipped: set[str] = set()
        self._failed: set[str] = set()
        self._started_at = datetime.now()
        self._output_dir: Optional[Path] = None

        for inp in workflow.get("inputs", []):
            name = inp["name"]
            value = cli_inputs.get(name, inp.get("default", ""))
            self.variables[name] = value

        self._by_id = {s["id"]: s for s in self.steps}

    # ---- DAG ----
    def _deps(self, step: dict) -> list[str]:
        return [d for d in step.get("depends_on", []) if d in self._by_id]

    def _layers(self) -> list[list[str]]:
        """按最长依赖路径分层，层内可并行。"""
        depth: dict[str, int] = {}
        for step in self.steps:
            deps = self._deps(step)
            depth[step["id"]] = 1 + max((depth.get(d, 0) for d in deps), default=0)
        layers: dict[int, list[str]] = {}
        for sid, d in depth.items():
            layers.setdefault(d, []).append(sid)
        return [layers[k] for k in sorted(layers)]

    def _step_done(self, step_id: str) -> bool:
        return step_id in self._step_results or step_id in self._skipped or step_id in self._failed

    def _layer_ready(self, layer: list[str]) -> bool:
        for sid in layer:
            step = self._by_id[sid]
            deps = self._deps(step)
            mode = step.get("depends_on_mode", "all")
            if mode == "any_completed":
                if deps and any(self._step_done(d) for d in deps):
                    continue
                return False
            if deps and not all(self._step_done(d) for d in deps):
                return False
        return True

    # ---- 执行 ----
    def run(self) -> None:
        self._output_dir = self._make_output_dir()
        summary: list[str] = [f"# {self.workflow.get('name', 'workflow')} 执行报告\n"]
        summary.append(f"- 开始时间：{self._started_at.strftime('%Y-%m-%d %H:%M:%S')}")
        summary.append(f"- 输入变量：{json.dumps(self.variables, ensure_ascii=False)}")
        summary.append("")

        remaining = set(self._by_id.keys())
        while remaining:
            # 找出当前可执行的层
            ready = [sid for sid in remaining
                     if all(self._step_done(d) for d in self._deps(self._by_id[sid]))]
            if not ready:
                block = [sid for sid in remaining
                         if not all(self._step_done(d) for d in self._deps(self._by_id[sid]))]
                raise RuntimeError(f"DAG 死锁，剩余步骤: {block}")

            # 交互节点串行（主线程），其余并行
            interactive = [sid for sid in ready if self._by_id[sid].get("type") in RESERVED_STEP_TYPES]
            parallel = [sid for sid in ready if sid not in interactive]

            if parallel:
                with ThreadPoolExecutor(max_workers=self.concurrency) as pool:
                    futures = {pool.submit(self._execute, sid): sid for sid in parallel}
                    for fut in as_completed(futures):
                        sid = futures[fut]
                        try:
                            fut.result()
                        except Exception as exc:  # noqa: BLE001
                            self._failed.add(sid)
                            print(f"  [失败] {sid}: {exc}", file=sys.stderr)
                            summary.append(f"## {sid} ❌ 失败\n\n```\n{exc}\n```\n")

            for sid in interactive:
                try:
                    self._execute(sid)
                except Exception as exc:  # noqa: BLE001
                    self._failed.add(sid)
                    print(f"  [失败] {sid}: {exc}", file=sys.stderr)
                    summary.append(f"## {sid} ❌ 失败\n\n```\n{exc}\n```\n")

            for sid in ready:
                remaining.discard(sid)

            if self._failed:
                break

        self._write_summary(summary)
        self._write_metadata()
        self._print_result()

    def _execute(self, step_id: str) -> None:
        step = self._by_id[step_id]
        step_type = step.get("type", "task")

        # condition 跳过
        if not eval_condition(step.get("condition"), self.variables):
            self._skipped.add(step_id)
            print(f"  [跳过] {step_id}（condition 不满足）")
            return

        print(f"  [执行] {step_id} (type={step_type}, role={step.get('role', '-')})")
        self._save_step_md(step_id, "# 准备执行\n")

        if step_type == "approval":
            self._run_approval(step)
            return
        if step_type == "human_input":
            self._run_human_input(step)
            return

        self._run_task(step)

    def _run_approval(self, step: dict) -> None:
        prompt = resolve_template(step.get("prompt", "是否放行？(y/n)"), self.variables)
        if self.interactive:
            answer = input(f"\n=== 审批门禁 [{step['id']}] ===\n{prompt}\n> ").strip().lower()
        else:
            print(f"\n=== 审批门禁 [{step['id']}]（非交互模式，自动放行）===\n{prompt}")
            answer = "y"
        if answer not in ("y", "yes", ""):
            raise RuntimeError(f"审批门禁 {step['id']} 被拒绝")
        self._step_results[step["id"]] = {"reply": "APPROVED", "type": "approval"}
        self._save_step_md(step["id"], f"## 审批通过\n\n{prompt}\n")

    def _run_human_input(self, step: dict) -> None:
        prompt = resolve_template(step.get("prompt", "请输入："), self.variables)
        if self.interactive:
            value = input(f"\n=== 人工输入 [{step['id']}] ===\n{prompt}\n> ")
        else:
            print(f"\n=== 人工输入 [{step['id']}]（非交互模式，用空串）===\n{prompt}")
            value = ""
        self._step_results[step["id"]] = {"reply": value, "type": "human_input"}
        with self._lock:
            self.variables[step["output"]] = value
        self._save_step_md(step["id"], f"## 人工输入\n\n{prompt}\n\n```\n{value}\n```\n")

    def _run_task(self, step: dict) -> None:
        agent_name = step["role"]
        agent_id = self.client.agent_id(agent_name)
        task_text = resolve_template(step.get("task", ""), self.variables)
        max_turns = int(step.get("max_turns", 4))
        extract = step.get("extract", "reply")

        # 指数退避重试（llm.retry 次）
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.retry + 1):
            try:
                session_id = self.client.create_session(agent_id, step["id"])
                reply = self._multi_turn(agent_id, session_id, task_text, max_turns)
                self._finish_task_step(step, reply, session_id, extract)
                return
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                print(f"    ↳ 第 {attempt}/{self.retry} 次失败: {exc}")
                if attempt < self.retry:
                    sleep_backoff(attempt)
        raise RuntimeError(f"重试 {self.retry} 次后仍失败: {last_exc}")

    def _multi_turn(self, agent_id: str, session_id: str, task_text: str, max_turns: int) -> str:
        """多轮对话：SOP 采集信息时员工会反问，直到无 awaiting_input 或达上限。"""
        message = task_text
        reply_parts: list[str] = []
        for turn_i in range(1, max_turns + 1):
            result = self.client.turn(session_id, message, timeout=self.turn_timeout)
            reply = (result.get("reply") or "").strip()
            if reply:
                reply_parts.append(reply)
            state = result.get("session_state") or {}
            awaiting = state.get("awaiting_input")
            if not awaiting:
                break
            # 员工在等用户提供信息：把员工的问题展示给操作员（非交互模式用空回答）
            question = reply[-2000:] if reply else str(awaiting)
            if self.interactive:
                print(f"    ↳ [{step_id_hint(session_id)}] 员工询问：{question[:200]}")
                answer = input("    ↳ 你的回答（直接回车结束本轮）: ").strip()
            else:
                answer = ""
            message = answer
            if not answer:
                break
        return "\n\n".join(reply_parts) or "(员工无文字回复，请查看 Trace)"

    def _finish_task_step(self, step: dict, reply: str, session_id: str, extract: str) -> None:
        trace = self.client.get_trace(session_id) if extract == "trace" else []
        value = reply
        if extract == "trace":
            value = json.dumps(trace, ensure_ascii=False, indent=2)
        with self._lock:
            self.variables[step["output"]] = value
            self._step_results[step["id"]] = {
                "reply": reply, "type": "task", "session_id": session_id,
                "trace": trace if extract == "trace" else None,
            }
        self._save_step_md(step["id"], self._step_md_content(step, reply, session_id))

    # ---- 归档 ----
    def _make_output_dir(self) -> Path:
        name = self.workflow.get("name", "workflow")
        stamp = self._started_at.strftime("%Y%m%d-%H%M%S")
        out = Path("ao-output") / f"{name}-{stamp}"
        (out / "steps").mkdir(parents=True, exist_ok=True)
        return out

    def _save_step_md(self, step_id: str, content: str) -> None:
        assert self._output_dir is not None
        order = list(self._by_id.keys()).index(step_id) + 1
        (self._output_dir / "steps" / f"{order}-{step_id}.md").write_text(
            content, encoding="utf-8"
        )

    @staticmethod
    def _step_md_content(step: dict, reply: str, session_id: str) -> str:
        return (
            f"## {step['id']}（role={step.get('role')}）\n\n"
            f"- 会话：{session_id}\n\n"
            f"### 回复\n\n{reply}\n"
        )

    def _write_summary(self, summary: list[str]) -> None:
        assert self._output_dir is not None
        for sid, result in self._step_results.items():
            status = "✅" if result.get("reply") else "⚠️"
            summary.append(f"- {sid}: {status} 类型={result.get('type', 'task')}")
        for sid in sorted(self._skipped):
            summary.append(f"- {sid}: ⏭️ 跳过（condition）")
        if self._failed:
            summary.append("")
            summary.append(f"❌ 失败步骤: {sorted(self._failed)}")
        (self._output_dir / "summary.md").write_text("\n".join(summary) + "\n", encoding="utf-8")

    def _write_metadata(self) -> None:
        assert self._output_dir is not None
        meta = {
            "name": self.workflow.get("name"),
            "started_at": self._started_at.isoformat(),
            "finished_at": datetime.now().isoformat(),
            "variables": self.variables,
            "steps": [
                {"id": s["id"], "role": s.get("role"),
                 "status": ("skipped" if s["id"] in self._skipped
                            else "failed" if s["id"] in self._failed else "done")}
                for s in self.steps
            ],
        }
        (self._output_dir / "metadata.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _print_result(self) -> None:
        assert self._output_dir is not None
        print(f"\n==== 执行结束 ====")
        for sid, result in self._step_results.items():
            marker = "✅" if result.get("reply") else "⚠️"
            print(f"  {marker} {sid}")
        for sid in sorted(self._skipped):
            print(f"  ⏭️  {sid}（跳过）")
        for sid in sorted(self._failed):
            print(f"  ❌ {sid}")
        print(f"输出目录: {self._output_dir.resolve()}")


def step_id_hint(session_id: str) -> str:
    return session_id


# ---------------------------------------------------------------- CLI

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="StaffDeck 数字员工流水线编排器（AO schema adapter）"
    )
    parser.add_argument("workflow", help="YAML 工作流文件，如 sdlc_pipeline.yaml")
    parser.add_argument("--base-url", default="http://127.0.0.1:5173")
    parser.add_argument("--username", default="admin")
    parser.add_argument("--password", default="admin")
    parser.add_argument("--tenant-id", default="tenant_demo")
    parser.add_argument("--input", action="append", default=[],
                        help="覆盖输入变量，k=v 形式，可多次")
    parser.add_argument("--dry-run", action="store_true", help="只解析并预览 DAG，不执行")
    parser.add_argument("--non-interactive", action="store_true",
                        help="审批自动放行、人工输入用空串")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    workflow = yaml.safe_load(Path(args.workflow).read_text(encoding="utf-8"))
    if not workflow or "steps" not in workflow:
        sys.exit("工作流无效：缺少 steps")

    cli_inputs = {}
    for kv in args.input:
        if "=" in kv:
            k, v = kv.split("=", 1)
            cli_inputs[k] = v

    if args.dry_run:
        print(f"工作流: {workflow.get('name')}")
        print(f"员工: {', '.join(sorted({s['role'] for s in workflow['steps'] if s.get('role')}))}")
        print(f"输入变量: {workflow.get('inputs', [])}")
        print("\n执行计划（分层）：")
        orchestrator = Orchestrator(workflow, client=None, cli_inputs=cli_inputs)  # type: ignore[arg-type]
        for i, layer in enumerate(orchestrator._layers()):
            desc = ", ".join(
                f"{sid}({'审批' if workflow['steps'] and next((s for s in workflow['steps'] if s['id'] == sid), {}).get('type') in RESERVED_STEP_TYPES else '并行' if len(layer) > 1 else '顺序'})"
                for sid in layer
            )
            print(f"  L{i+1}: {desc}")
        print("\n--dry-run 结束，未执行任何调用。")
        return

    client = StaffDeckClient(args.base_url, args.username, args.password, args.tenant_id)
    orchestrator = Orchestrator(workflow, client, cli_inputs, interactive=not args.non_interactive)
    orchestrator.run()


if __name__ == "__main__":
    main()
