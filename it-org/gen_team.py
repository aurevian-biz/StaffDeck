#!/usr/bin/env python3
"""
StaffDeck 数字员工团队生成脚本

按 org_agents.json 中的员工声明创建/更新一个团队，并在团队黑板写入
「共享项目目录约定」，让成员使用绝对路径共享同一份项目产出。

用法：
  python gen_team.py                                   # 使用默认团队配置（软件系统开发团队）
  python gen_team.py --team-name "增长团队" --leader "产品经理" \
      --members "方案架构师" --members "软件工程师"      # 自定义团队
  python gen_team.py --shared-dir /srv/staffdeck-project   # 指定共享项目目录
  python gen_team.py --dry-run                         # 只检查连接与配置，不创建资源

幂等性：
  - 同名团队已存在时复用（不重建）；成员/leader 已就位时跳过。
  - 黑板「共享项目目录约定」为去重条目（内容相同/互为子串时不重复写入）。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).resolve().parent

DEFAULT_TEAM_NAME = "软件系统开发团队"
DEFAULT_LEADER = "交付项目经理"
DEFAULT_MEMBERS = [
    "产品经理",
    "方案架构师",
    "后端架构师",
    "软件工程师",
    "前端开发工程师",
    "数据库优化工程师",
    "DevOps 自动化工程师",
    "代码审查专家",
    "API 测试工程师",
]
DEFAULT_SHARED_DIR = "/srv/staffdeck-project"


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


class TeamGenerator:
    def __init__(
        self,
        base_url: str,
        tenant_id: str,
        username: str,
        password: str,
        dry_run: bool = False,
    ):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.username = username
        self.password = password
        self.dry_run = dry_run
        self.session = requests.Session()
        self.token: str | None = None

    # ---------- HTTP 基础 ----------
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _req(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return self.session.request(
            method, f"{self.base_url}{path}", headers=self._headers(), timeout=30, **kwargs
        )

    def _handle(self, label: str, resp: requests.Response, ok: set[int]) -> dict[str, Any] | None:
        if resp.status_code in ok:
            if resp.content:
                try:
                    return resp.json()
                except ValueError:
                    return None
            return None
        detail = ""
        try:
            detail = json.dumps(resp.json(), ensure_ascii=False)[:300]
        except ValueError:
            detail = resp.text[:300]
        raise RuntimeError(f"{label} 失败 HTTP {resp.status_code}: {detail}")

    # ---------- 认证 ----------
    def login(self) -> None:
        resp = self._req(
            "POST",
            "/api/auth/login",
            json={"tenant_id": self.tenant_id, "username": self.username, "password": self.password},
        )
        data = self._handle("登录", resp, {200})
        self.token = str((data or {}).get("token") or "")
        if not self.token and not self.dry_run:
            raise RuntimeError("登录未返回 token")
        eprint(f"[login] 已登录 {self.username}@{self.tenant_id}")

    # ---------- 员工解析 ----------
    def list_agents(self) -> dict[str, dict[str, Any]]:
        """GET 全部员工，返回 {name: {id, ...}}。"""
        resp = self._req(
            "GET",
            "/api/enterprise/agents",
            params={"tenant_id": self.tenant_id},
        )
        data = self._handle("员工列表", resp, {200})
        agents = data if isinstance(data, list) else (data or {}).get("agents") or []
        return {str(a.get("name")): a for a in agents if isinstance(a, dict) and a.get("id")}

    def resolve_agent(self, agents: dict[str, dict[str, Any]], name: str) -> str:
        agent = agents.get(name)
        if agent is None:
            raise RuntimeError(f"员工不存在: {name}（请先运行 import_staffdeck.py 导入 org_agents.json）")
        return str(agent["id"])

    # ---------- 团队 ----------
    def list_teams(self) -> list[dict[str, Any]]:
        resp = self._req(
            "GET",
            "/api/enterprise/teams",
            params={"tenant_id": self.tenant_id},
        )
        data = self._handle("团队列表", resp, {200})
        return data if isinstance(data, list) else []

    def find_team(self, name: str) -> dict[str, Any] | None:
        for team in self.list_teams():
            if str(team.get("name")) == name:
                return team
        return None

    def create_team(self, name: str, description: str) -> dict[str, Any]:
        resp = self._req(
            "POST",
            "/api/enterprise/teams",
            json={
                "tenant_id": self.tenant_id,
                "name": name,
                "description": description,
                "config": {},
            },
        )
        data = self._handle("创建团队", resp, {200, 201})
        eprint(f"[team] 已创建团队: {name} ({data.get('id')})")
        return data or {}

    def add_member(self, team_id: str, agent_id: str, role: str) -> None:
        resp = self._req(
            "POST",
            f"/api/enterprise/teams/{team_id}/members",
            json={"tenant_id": self.tenant_id, "agent_id": agent_id, "role": role},
        )
        try:
            self._handle("添加成员", resp, {200, 201})
            eprint(f"[member] 已添加成员 role={role} agent={agent_id}")
        except RuntimeError as exc:
            if "already" in str(exc).lower() or resp.status_code == 409:
                eprint(f"[member] 成员已存在，跳过 agent={agent_id}")
            else:
                raise

    def list_members(self, team_id: str) -> list[dict[str, Any]]:
        resp = self._req(
            "GET",
            f"/api/enterprise/teams/{team_id}",
            params={"tenant_id": self.tenant_id},
        )
        data = self._handle("团队详情", resp, {200})
        return data.get("members") if isinstance(data, dict) and data.get("members") else []

    def set_leader(self, team_id: str, agent_id: str, agent_name: str) -> None:
        # leader 必须先作为成员存在（服务端 404 "Agent is not a team member"）。
        self.add_member(team_id, agent_id, "member")
        members = self.list_members(team_id)
        leader_ready = any(
            str(m.get("agent_id")) == agent_id and str(m.get("role")) == "leader"
            for m in members
        )
        if leader_ready:
            eprint(f"[leader] leader 已就位，跳过: {agent_name}")
            return
        resp = self._req(
            "PUT",
            f"/api/enterprise/teams/{team_id}/leader",
            json={"tenant_id": self.tenant_id, "agent_id": agent_id},
        )
        self._handle("设置 leader", resp, {200})
        eprint(f"[leader] 已设置 leader: {agent_name}")

    # ---------- 黑板 ----------
    def write_blackboard(self, team_id: str, content: str, tags: list[str]) -> None:
        resp = self._req(
            "POST",
            f"/api/enterprise/teams/{team_id}/blackboard",
            json={"tenant_id": self.tenant_id, "content": content, "tags": tags},
        )
        data = self._handle("写黑板", resp, {200, 201})
        written = (data or {}).get("entries") or []
        skipped = (data or {}).get("skipped") or []
        if written:
            eprint(f"[blackboard] 黑板条目已写入: {len(written)} 条")
        if skipped:
            eprint(f"[blackboard] 黑板条目跳过(去重): {len(skipped)} 条")

    # ---------- 共享目录约定 ----------
    def shared_dir_agreement(self, shared_dir: str, team_name: str) -> tuple[str, list[str]]:
        content = (
            f"共享项目目录约定（团队「{team_name}」全体成员必须遵守）：\n"
            f"1) 项目全部产出写入共享目录 {shared_dir}，成员间通过绝对路径互访：\n"
            f"   read_file/write_file/list_directory 均接受宿主机绝对路径，"
            f"相对路径只指向各自任务私有工作区，成员之间互不可见；\n"
            f"2) 完成任务时把新增/修改的文件路径、sha256 与变更说明写进完成报告，"
            f"方便依赖任务的成员定位产物；\n"
            f"3) 共享目录内不要使用符号链接（Harness 拒绝 symlink）；\n"
            f"4) 目录清单用 list_directory 绝对路径查询（glob 模式仅限任务工作区，"
            f"不能跨目录搜索）；\n"
            f"5) 读写受宿主机文件权限约束，遇到无权访问时上报 TL 转人工处理，"
            f"不得改用私有工作区绕开约定。"
        )
        return content, ["shared-dir", "collaboration", team_name]

    # ---------- 主流程 ----------
    def run(
        self,
        team_name: str,
        description: str,
        leader_name: str,
        member_names: list[str],
        shared_dir: str,
    ) -> None:
        if self.dry_run:
            eprint("[dry-run] 跳过全部写操作")
            return

        agents = self.list_agents()
        leader_id = self.resolve_agent(agents, leader_name)
        member_ids = [(name, self.resolve_agent(agents, name)) for name in member_names]

        team = self.find_team(team_name)
        if team is not None:
            team_id = str(team["id"])
            eprint(f"[team] 复用已有团队: {team_name} ({team_id})")
        else:
            team = self.create_team(team_name, description)
            team_id = str(team["id"])

        self.set_leader(team_id, leader_id, leader_name)
        for name, agent_id in member_ids:
            if agent_id == leader_id:
                continue
            self.add_member(team_id, agent_id, "member")

        content, tags = self.shared_dir_agreement(shared_dir, team_name)
        self.write_blackboard(team_id, content, tags)
        eprint(f"[done] 团队「{team_name}」就绪: leader={leader_name} members={len(member_names)} 共享目录={shared_dir}")


def load_org_config() -> dict[str, Any]:
    path = HERE / "org_config.json"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def main(argv: list[str] | None = None) -> int:
    config = load_org_config()
    meta = config.get("meta", {}) if isinstance(config, dict) else {}

    parser = argparse.ArgumentParser(description="StaffDeck 团队生成脚本")
    parser.add_argument("--base-url", default=meta.get("base_url", "http://127.0.0.1:5173"))
    parser.add_argument("--username", default=meta.get("admin_username", "admin"))
    parser.add_argument("--password", default=meta.get("admin_password", "admin"))
    parser.add_argument("--tenant-id", default=meta.get("tenant_id", "tenant_demo"))
    parser.add_argument("--team-name", default=DEFAULT_TEAM_NAME)
    parser.add_argument("--leader", default=DEFAULT_LEADER)
    parser.add_argument("--members", action="append", default=None, help="成员员工名，可多次指定")
    parser.add_argument("--shared-dir", default=DEFAULT_SHARED_DIR, help="共享项目目录绝对路径")
    parser.add_argument("--dry-run", action="store_true", help="只检查配置与连接")
    args = parser.parse_args(argv)

    members = args.members or list(DEFAULT_MEMBERS)
    description = (
        f"数字员工软件开发团队：leader={args.leader}，成员 {len(members)} 人，"
        f"共享项目目录 {args.shared_dir}。"
    )

    gen = TeamGenerator(args.base_url, args.tenant_id, args.username, args.password, dry_run=args.dry_run)
    try:
        gen.login()
        gen.run(
            team_name=args.team_name,
            description=description,
            leader_name=args.leader,
            member_names=members,
            shared_dir=args.shared_dir,
        )
        return 0
    except RuntimeError as exc:
        eprint(f"[error] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())