#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
convert_opencode_skills.py
将 opencode 用户技能（SKILL.md + references/ + scripts/）批量转换为
StaffDeck 通用技能（GeneralSkill）JSON 配置。

用法:
    python3 it-org/convert_opencode_skills.py \
        --skills-dir ~/.config/opencode/skills \
        --out it-org/org_general_skills_new.json \
        --group A,B   # 或 --all

输出格式（与 it-org/org_general_skills.json 主文件一致，list）:
    [{"name","slug","description","markdown","files":[{"path","content","size","mime_type"}],"status"}]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

MAX_FILE_BYTES = 1024 * 1024  # 单文件超过 1MB 跳过并警告

# ---------------------------------------------------------------- frontmatter

def parse_frontmatter(text: str) -> tuple[dict, str]:
    """解析 SKILL.md 的 YAML frontmatter（--- 块），返回 (meta, body)。"""
    meta: dict = {}
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            raw = text[3:end]
            body = text[end + 4 :]
            for line in raw.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip().strip("'\"")
                if value.lower() in ("true", "false"):
                    value = value.lower() == "true"
                meta[key] = value
            return meta, body
    return meta, text


# ---------------------------------------------------------------- collect files

def collect_files(skill_dir: Path) -> list[dict]:
    """递归收集技能目录下所有文件（SKILL.md 置首），超过大小限制的跳过。"""
    files: list[dict] = []
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(skill_dir).as_posix()
        data = p.read_bytes()
        if len(data) > MAX_FILE_BYTES:
            print(f"  [warn] 跳过超大文件 {rel} ({len(data)} bytes > {MAX_FILE_BYTES})")
            continue
        try:
            content = data.decode("utf-8")
        except UnicodeDecodeError:
            content = data.decode("utf-8", errors="replace")
        mime = "text/markdown" if rel.endswith(".md") else (
            "application/json" if rel.endswith(".json") else "text/plain"
        )
        files.append({
            "path": rel,
            "content": content,
            "size": len(data),
            "mime_type": mime,
        })
    # SKILL.md 置首
    files.sort(key=lambda f: (f["path"] != "SKILL.md", f["path"]))
    return files


# ---------------------------------------------------------------- build skill

def build_general_skill(skill_dir: Path) -> dict:
    skill_md_path = skill_dir / "SKILL.md"
    if not skill_md_path.exists():
        raise FileNotFoundError(f"{skill_dir} 缺少 SKILL.md")
    text = skill_md_path.read_text(encoding="utf-8")
    meta, _body = parse_frontmatter(text)
    name = meta.get("name") or skill_dir.name
    description = meta.get("description") or f"opencode 技能 {name} 迁移"
    files = collect_files(skill_dir)
    # files 必须包含 SKILL.md（后端 _normalize_skill_files 强制）
    if not any(f["path"] == "SKILL.md" for f in files):
        files.insert(0, {
            "path": "SKILL.md",
            "content": text,
            "size": len(text.encode("utf-8")),
            "mime_type": "text/markdown",
        })
    return {
        "name": name,
        "slug": skill_dir.name,
        "description": description,
        "markdown": text,
        "files": files,
        "status": "published",
    }


# ---------------------------------------------------------------- group defs

# A 组：纯方法论（SKILL.md + references，无外部环境依赖）
GROUP_A = [
    "ce-brainstorm", "ce-plan", "ce-ideate", "ce-debug", "ce-code-review",
    "ce-simplify-code", "ce-doc-review", "ce-strategy",
    "ce-agent-native-architecture", "ce-agent-native-audit",
    "ce-dhh-rails-style", "reviewing-openspec-artifacts",
]

# B 组：带脚本但脚本自包含（SKILL.md + scripts/，可随 files 打包迁移）
GROUP_B = [
    "ce-commit", "ce-commit-push-pr", "ce-clean-gone-branches", "ce-worktree",
    "ce-compound", "ce-compound-refresh", "ce-release-notes", "ce-setup",
    "ce-riffrec-feedback-analysis", "ce-optimize",
]


def main() -> int:
    ap = argparse.ArgumentParser(description="opencode 技能 → StaffDeck 通用技能")
    ap.add_argument("--skills-dir", default="~/.config/opencode/skills",
                    help="opencode 技能根目录（默认 ~/.config/opencode/skills）")
    ap.add_argument("--out", default="it-org/org_general_skills_new.json",
                    help="输出 JSON 路径")
    ap.add_argument("--group", default="A,B",
                    help="转换分组：A 或 B 或 A,B（默认 A,B）")
    ap.add_argument("--all", action="store_true", help="转换 skills-dir 下全部技能")
    args = ap.parse_args()

    base = Path(args.skills_dir).expanduser()
    if not base.is_dir():
        print(f"[error] 技能目录不存在: {base}")
        return 1

    if args.all:
        names = sorted(p.name for p in base.iterdir() if p.is_dir() and (p / "SKILL.md").exists())
    else:
        names = []
        for g in args.group.split(","):
            g = g.strip().upper()
            if g == "A":
                names += GROUP_A
            elif g == "B":
                names += GROUP_B
            else:
                print(f"[warn] 未知分组 {g}，忽略")
        # 去重保序
        seen: set[str] = set()
        names = [n for n in names if not (n in seen or seen.add(n))]

    skills = []
    missing = []
    for n in names:
        d = base / n
        if not d.is_dir() or not (d / "SKILL.md").exists():
            missing.append(n)
            continue
        try:
            sk = build_general_skill(d)
            skills.append(sk)
            nfiles = len(sk["files"])
            print(f"  [ok] {sk['slug']:40s} files={nfiles:2d} markdown={len(sk['markdown'])}B")
        except Exception as e:  # noqa: BLE001
            print(f"  [fail] {n}: {e}")

    if missing:
        print(f"[warn] 缺失技能目录（跳过）: {', '.join(missing)}")

    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n完成: {len(skills)} 个通用技能 → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
