#!/usr/bin/env python3
"""
StaffDeck 数字员工组织配置导入脚本

按 org_config.json 中声明的顺序导入：
  knowledge_bases -> tools -> general_skills -> skills -> agents -> bindings

用法：
  python import_staffdeck.py                          # 使用 org_config.json 中的连接信息
  python import_staffdeck.py --base-url http://127.0.0.1:5173 --username admin --password admin --tenant-id tenant_demo
  python import_staffdeck.py --dry-run                # 只校验配置与登录，不创建任何资源

幂等性：同名资源/员工已存在时跳过创建；绑定使用 PUT 全量替换，重复执行结果一致。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import requests

HERE = Path(__file__).resolve().parent


def eprint(msg: str) -> None:
    print(msg, file=sys.stderr)


class Importer:
    def __init__(self, base_url: str, tenant_id: str, username: str, password: str, dry_run: bool = False):
        self.base_url = base_url.rstrip("/")
        self.tenant_id = tenant_id
        self.username = username
        self.password = password
        self.dry_run = dry_run
        self.session = requests.Session()
        self.token: str | None = None
        # 业务键 -> 内部主键 id 映射（绑定 PUT 只认内部 id）
        self.resolved: dict[str, str] = {}
        self.overall_agents: set[str] = set()

    # ---------- HTTP 基础 ----------
    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json"}
        if self.token:
            h["Authorization"] = f"Bearer {self.token}"
        return h

    def _req(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        resp = self.session.request(method, f"{self.base_url}{path}", headers=self._headers(), timeout=30, **kwargs)
        return resp

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

    # ---------- 各阶段 ----------
    def _probe_ports(self) -> list[str]:
        """在 5173-5199 范围内探测 StaffDeck 服务（官方默认 5173，冲突顺延 5174-5199）。"""
        from urllib.parse import urlparse

        parsed = urlparse(self.base_url)
        host = parsed.hostname or "127.0.0.1"
        found: list[str] = []
        for port in range(5173, 5200):
            if port == (parsed.port or 5173):
                continue
            try:
                resp = self.session.get(f"http://{host}:{port}/api/health", timeout=2)
                if resp.status_code == 200:
                    found.append(f"http://{host}:{port}")
            except requests.RequestException:
                continue
        return found

    def health_check(self) -> None:
        if self.dry_run:
            print("[dry-run] 跳过健康检查")
            return
        try:
            resp = self._req("GET", "/api/health")
        except requests.ConnectionError:
            found = self._probe_ports()
            if found:
                print(f"[错误] 无法连接 {self.base_url}（服务可能监听在其他端口）")
                print(f"       在以下端口探测到 StaffDeck 服务:")
                for url in found:
                    print(f"         - {url}")
                print(f"       请用 --base-url 指定正确地址重试，例如:")
                print(f"         python it-org/import_staffdeck.py --base-url {found[0]}")
            else:
                print(f"[错误] 无法连接 {self.base_url}，且 5173-5199 端口均未探测到服务")
                print(f"       请确认 StaffDeck 已启动（scripts/dev_up.sh 或桌面安装包），且")
                print(f"       启动完成后稍等数秒再运行本脚本。")
            raise
        if resp.status_code != 200:
            raise RuntimeError(f"服务不可达: GET /api/health -> HTTP {resp.status_code}")
        print(f"[ok] 服务健康: {resp.text[:80]}")

    def login(self) -> None:
        if self.dry_run:
            print("[dry-run] 跳过登录")
            return
        resp = self._req("POST", "/api/auth/login", json={
            "tenant_id": self.tenant_id,
            "username": self.username,
            "password": self.password,
        })
        data = self._handle("登录", resp, {200})
        self.token = (data or {}).get("token")
        if not self.token:
            raise RuntimeError("登录成功但未返回 token")
        print(f"[ok] 登录成功: {self.username}@{self.tenant_id}")

    # ---------- 知识库 ----------
    def _existing_kb_by_name(self) -> dict[str, str]:
        resp = self._req("GET", "/api/enterprise/knowledge-bases", params={"tenant_id": self.tenant_id})
        data = self._handle("查询知识库列表", resp, {200})
        return {kb["name"]: kb["id"] for kb in data or []}

    def import_knowledge_bases(self, items: list[dict[str, Any]]) -> None:
        existing = {} if self.dry_run else self._existing_kb_by_name()
        for kb in items:
            name = kb["name"]
            if name in existing:
                self.resolved[f"kb:{name}"] = existing[name]
                print(f"[skip] 知识库已存在: {name} (id={existing[name]})")
                continue
            if self.dry_run:
                self.resolved[f"kb:{name}"] = f"<dry:{name}>"
                print(f"[dry-run] 将创建知识库: {name}")
                continue
            resp = self._req("POST", "/api/enterprise/knowledge-bases", json={
                "tenant_id": self.tenant_id,
                "name": name,
                "description": kb.get("description"),
                "metadata": kb.get("metadata", {}),
            })
            data = self._handle(f"创建知识库 {name}", resp, {200, 201})
            self.resolved[f"kb:{name}"] = data["id"]
            print(f"[ok] 知识库创建: {name} (id={data['id']})")

    # ---------- 工具 ----------
    def _existing_tool_by_name(self) -> dict[str, str]:
        resp = self._req("GET", "/api/enterprise/tools", params={"tenant_id": self.tenant_id})
        data = self._handle("查询工具列表", resp, {200})
        return {t["name"]: t["id"] for t in data or []}

    def import_tools(self, items: list[dict[str, Any]]) -> None:
        existing = {} if self.dry_run else self._existing_tool_by_name()
        for tool in items:
            name = tool["name"]
            if name in existing:
                self.resolved[f"tool:{name}"] = existing[name]
                print(f"[skip] 工具已存在: {name} (id={existing[name]})")
                continue
            if self.dry_run:
                self.resolved[f"tool:{name}"] = f"<dry:{name}>"
                print(f"[dry-run] 将创建工具: {name}")
                continue
            body = {k: v for k, v in tool.items() if k != "name" or True}
            body["tenant_id"] = self.tenant_id
            resp = self._req("POST", "/api/enterprise/tools", json=body)
            data = self._handle(f"创建工具 {name}", resp, {200, 201})
            self.resolved[f"tool:{name}"] = data["id"]
            print(f"[ok] 工具创建: {name} (id={data['id']})")

    # ---------- 通用技能 ----------
    def _existing_general_skill_by_slug(self) -> dict[str, str]:
        resp = self._req("GET", "/api/enterprise/general-skills", params={"tenant_id": self.tenant_id})
        data = self._handle("查询通用技能列表", resp, {200})
        return {g["slug"]: g["id"] for g in data or []}

    def import_general_skills(self, items: list[dict[str, Any]]) -> None:
        existing = {} if self.dry_run else self._existing_general_skill_by_slug()
        for gs in items:
            slug = gs["slug"]
            if slug in existing:
                self.resolved[f"gs:{slug}"] = existing[slug]
                print(f"[skip] 通用技能已存在: {slug} (id={existing[slug]})")
                continue
            if self.dry_run:
                self.resolved[f"gs:{slug}"] = f"<dry:{slug}>"
                print(f"[dry-run] 将导入通用技能: {slug}")
                continue
            files = list(gs.get("files", []) or [])
            markdown = gs.get("markdown", "") or ""
            if not any(f.get("path") == "SKILL.md" for f in files):
                files.insert(0, {"path": "SKILL.md", "content": markdown})
            body = {
                "tenant_id": self.tenant_id,
                "name": gs["name"],
                "slug": slug,
                "description": gs.get("description"),
                "markdown": markdown,
                "files": files,
                "status": gs.get("status", "published"),
            }
            resp = self._req("POST", "/api/enterprise/general-skills/import", json=body)
            data = self._handle(f"导入通用技能 {slug}", resp, {200, 201})
            self.resolved[f"gs:{slug}"] = data["id"]
            print(f"[ok] 通用技能导入: {slug} (id={data['id']})")

    # ---------- SOP 技能 ----------
    def _existing_skill_by_skill_id(self) -> dict[str, str]:
        resp = self._req("GET", "/api/enterprise/skills", params={"tenant_id": self.tenant_id})
        data = self._handle("查询技能列表", resp, {200})
        return {s["skill_id"]: s["id"] for s in data or []}

    def import_skills(self, items: list[dict[str, Any]]) -> None:
        existing = {} if self.dry_run else self._existing_skill_by_skill_id()
        for item in items:
            content = item["content"]
            skill_id = content["skill_id"]
            if skill_id in existing:
                self.resolved[f"skill:{skill_id}"] = existing[skill_id]
                print(f"[skip] SOP 技能已存在: {skill_id} (id={existing[skill_id]})")
                continue
            if self.dry_run:
                self.resolved[f"skill:{skill_id}"] = f"<dry:{skill_id}>"
                print(f"[dry-run] 将创建 SOP 技能: {skill_id}")
                continue
            resp = self._req("POST", "/api/enterprise/skills", json={
                "tenant_id": self.tenant_id,
                "content": content,
                "status": item.get("status", "published"),
            })
            data = self._handle(f"创建 SOP 技能 {skill_id}", resp, {200, 201})
            self.resolved[f"skill:{skill_id}"] = data["id"]
            print(f"[ok] SOP 技能创建: {skill_id} (id={data['id']})")

    # ---------- 员工 ----------
    def _existing_agents_by_name(self) -> dict[str, str]:
        resp = self._req("GET", "/api/enterprise/agents", params={"tenant_id": self.tenant_id})
        data = self._handle("查询员工列表", resp, {200})
        return {a["name"]: a["id"] for a in data or []}

    def import_agents(self, items: list[dict[str, Any]]) -> None:
        existing = {} if self.dry_run else self._existing_agents_by_name()
        for agent in items:
            name = agent["name"]
            if agent.get("is_overall"):
                # 整体员工走全局资源池，绑定/能力由其下的开放广场资源自动构成
                self.overall_agents.add(name)
            if name in existing:
                self.resolved[f"agent:{name}"] = existing[name]
                print(f"[skip] 员工已存在: {name} (id={existing[name]})")
                continue
            if self.dry_run:
                self.resolved[f"agent:{name}"] = f"<dry:{name}>"
                print(f"[dry-run] 将创建员工: {name}")
                continue
            resp = self._req("POST", "/api/enterprise/agents", json={
                "tenant_id": self.tenant_id,
                "name": name,
                "description": agent.get("description"),
                "persona_prompt": agent.get("persona_prompt"),
                "is_overall": agent.get("is_overall", False),
                "source_mode": agent.get("source_mode", "blank"),
                "copy_from_agent_id": agent.get("copy_from_agent_id"),
                "metadata": agent.get("metadata", {}),
            })
            data = self._handle(f"创建员工 {name}", resp, {200, 201})
            self.resolved[f"agent:{name}"] = data["id"]
            print(f"[ok] 员工创建: {name} (id={data['id']})")

    # ---------- 绑定 ----------
    def _resolve(self, resource_type: str, resource_id: str) -> str:
        key_map = {
            "skill": f"skill:{resource_id}",
            "general_skill": f"gs:{resource_id}",
            "knowledge_base": f"kb:{resource_id}",
            "tool": f"tool:{resource_id}",
        }
        key = key_map[resource_type]
        if key not in self.resolved:
            raise RuntimeError(f"无法解析资源 {resource_type}:{resource_id}（请确认已先导入）")
        return self.resolved[key]

    def import_bindings(self, bindings: dict[str, list[dict[str, Any]]]) -> None:
        for agent_name, resources in bindings.items():
            agent_key = f"agent:{agent_name}"
            if agent_key not in self.resolved:
                eprint(f"[warn] 跳过绑定：员工 {agent_name} 不存在（可能创建失败）")
                continue
            if agent_name in self.overall_agents:
                print(f"[skip] 整体员工 {agent_name} 使用全局资源池，无需手动绑定")
                continue
            if self.dry_run:
                print(f"[dry-run] 将绑定 {len(resources)} 项资源到员工: {agent_name}")
                continue
            payload = []
            for r in resources:
                payload.append({
                    "resource_type": r["resource_type"],
                    "resource_id": self._resolve(r["resource_type"], r["resource_id"]),
                    "status": r.get("status", "active"),
                    "metadata": r.get("metadata", {}),
                })
            resp = self._req("PUT", f"/api/enterprise/agents/{self.resolved[agent_key]}/resources", json={
                "tenant_id": self.tenant_id,
                "resources": payload,
            })
            self._handle(f"绑定资源到 {agent_name}", resp, {200})
            print(f"[ok] 员工 {agent_name} 绑定 {len(payload)} 项资源")


def load_config(cfg_dir: Path) -> tuple[dict[str, Any], dict[str, list[Any]]]:
    config = json.loads((cfg_dir / "org_config.json").read_text(encoding="utf-8"))
    files = config["files"]
    data: dict[str, list[Any]] = {}
    for key, filename in files.items():
        data[key] = json.loads((cfg_dir / filename).read_text(encoding="utf-8"))
    return config, data


def main() -> int:
    parser = argparse.ArgumentParser(description="导入 StaffDeck 数字员工组织配置")
    parser.add_argument("--config-dir", type=Path, default=HERE, help="配置目录（默认脚本所在目录）")
    parser.add_argument("--base-url", help="StaffDeck 地址（默认取 org_config.json）")
    parser.add_argument("--username", help="管理员用户名（默认 admin）")
    parser.add_argument("--password", help="管理员密码（默认 admin）")
    parser.add_argument("--tenant-id", help="租户 ID（默认取 org_config.json）")
    parser.add_argument("--dry-run", action="store_true", help="只校验配置与登录，不创建资源")
    args = parser.parse_args()

    config, data = load_config(args.config_dir)
    meta = config["meta"]

    importer = Importer(
        base_url=args.base_url or meta["base_url"],
        tenant_id=args.tenant_id or meta["tenant_id"],
        username=args.username or meta.get("admin_username", "admin"),
        password=args.password or meta.get("admin_password", "admin"),
        dry_run=args.dry_run,
    )

    print(f"== StaffDeck 组织导入: {meta.get('org_name', '')} @ {importer.base_url} ==")
    if importer.dry_run:
        print("== DRY-RUN 模式：只校验配置结构，不调用创建 API ==")

    try:
        importer.health_check()
        importer.login()
    except RuntimeError as exc:
        eprint(f"[error] {exc}")
        return 1

    steps = {
        "knowledge_bases": importer.import_knowledge_bases,
        "tools": importer.import_tools,
        "general_skills": importer.import_general_skills,
        "skills": importer.import_skills,
        "agents": importer.import_agents,
        "bindings": importer.import_bindings,
    }
    order = meta.get("import_order", list(steps.keys()))

    for step in order:
        if step not in steps:
            eprint(f"[warn] 未知导入阶段: {step}")
            continue
        try:
            steps[step](data[step])
        except RuntimeError as exc:
            eprint(f"[error] 阶段 {step} 失败: {exc}")
            return 1
        except KeyError as exc:
            eprint(f"[error] 阶段 {step} 缺少配置数据: {exc}")
            return 1

    print("== 导入完成 ==")
    if not importer.dry_run:
        print(f"   员工: {sum(1 for k in importer.resolved if k.startswith('agent:'))} 个已就绪")
        print(f"   资源: {sum(1 for k in importer.resolved if not k.startswith('agent:'))} 项已解析")
    return 0


if __name__ == "__main__":
    sys.exit(main())
