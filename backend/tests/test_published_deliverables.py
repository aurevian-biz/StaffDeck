"""Tests for the list_published_deliverables internal capability.

The capability answers "what deliverables has this session already published?"
by scanning assistant messages' harness_artifacts metadata across task frames,
so a digital employee can enumerate its own past deliveries instead of claiming
it cannot find documents it delivered hours ago.
"""

import hashlib
from datetime import timedelta

from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.capability_manifest import CapabilityManifestBuilder
from app.core.harness_capability_invoker import HarnessCapabilityInvoker
from app.db.models import (
    ChatSession,
    Message,
    ModelConfig,
    new_id,
    utc_now,
)


def _test_engine():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


def _chat_session(**updates: object) -> ChatSession:
    values: dict[str, object] = {
        "id": "session-1",
        "tenant_id": "tenant-demo",
    }
    values.update(updates)
    return ChatSession(**values)


def _model_config() -> ModelConfig:
    return ModelConfig(
        id="model-test",
        tenant_id="tenant-demo",
        name="测试模型",
        api_key_encrypted="test",
        model="test-model",
    )


def _artifact(
    task_frame_id: str,
    path: str,
    *,
    operation: str = "publish_artifact",
) -> dict[str, object]:
    content = f"# {path}\n".encode("utf-8")
    return {
        "type": "workspace_file",
        "task_frame_id": task_frame_id,
        "path": path,
        "sha256": hashlib.sha256(content).hexdigest(),
        "size": len(content),
        "operation": operation,
        "sandbox_path": f"/workspace/{path}",
        "display_name": path,
        "description": f"generated {path}",
        "content_type": "text/markdown",
    }


def _build_invoker(db: Session) -> HarnessCapabilityInvoker:
    manifest = CapabilityManifestBuilder(db).build(
        "tenant-demo",
        None,
        None,
        None,
    )
    return HarnessCapabilityInvoker(
        db,
        tenant_id="tenant-demo",
        session=_chat_session(),
        task_frame_id="task-current",
        model_config=_model_config(),
        manifest=manifest,
        active_skill=None,
        active_step_id=None,
        agent_id=None,
    )


def test_list_published_deliverables_returns_cross_task_frame_artifacts(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        db.add(
            Message(
                id=new_id("msg"),
                tenant_id="tenant-demo",
                session_id="session-1",
                role="assistant",
                content="第一轮：生成了需求文档",
                metadata_json={
                    "harness_artifacts": [
                        _artifact("task-old-1", "需求发现与问题定义.md"),
                        _artifact("task-old-1", "方案设计与PRD.md"),
                    ],
                    "task_frame_ids": ["task-old-1"],
                },
            )
        )
        db.add(
            Message(
                id=new_id("msg"),
                tenant_id="tenant-demo",
                session_id="session-1",
                role="assistant",
                content="第二轮：投递了排期文档",
                metadata_json={
                    "harness_artifacts": [
                        _artifact("task-old-2", "开发排期文档.md"),
                    ],
                    "task_frame_ids": ["task-old-2"],
                },
            )
        )
        db.commit()
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {})

    assert result["success"] is True
    data = result["data"]
    assert data["count"] == 3
    paths = {item["path"] for item in data["deliverables"]}
    assert paths == {
        "需求发现与问题定义.md",
        "方案设计与PRD.md",
        "开发排期文档.md",
    }
    frames = {item["task_frame_id"] for item in data["deliverables"]}
    assert frames == {"task-old-1", "task-old-2"}
    assert all(item["type"] == "workspace_file" for item in data["deliverables"])


def test_list_published_deliverables_serializes_rich_artifact_fields(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        artifact = _artifact("task-old-1", "干系人对齐与路线图排期.md")
        db.add(
            Message(
                id=new_id("msg"),
                tenant_id="tenant-demo",
                session_id="session-1",
                role="assistant",
                content="发布干系人对齐文档",
                metadata_json={"harness_artifacts": [artifact]},
            )
        )
        db.commit()
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {"limit": 10})

    assert result["success"] is True
    item = result["data"]["deliverables"][0]
    assert item["display_name"] == "干系人对齐与路线图排期.md"
    assert item["content_type"] == "text/markdown"
    assert item["sha256"] == artifact["sha256"]
    assert item["size"] == artifact["size"]


def test_list_published_deliverables_empty_session_returns_empty(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {})

    assert result["success"] is True
    assert result["data"] == {"deliverables": [], "count": 0}


def test_list_published_deliverables_ignores_other_tenants_and_user_messages(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        # Belongs to another tenant -- must be excluded.
        db.add(
            Message(
                id=new_id("msg"),
                tenant_id="tenant-other",
                session_id="session-1",
                role="assistant",
                content="其他租户的产物",
                metadata_json={
                    "harness_artifacts": [_artifact("task-x", "other.md")]
                },
            )
        )
        # User message in the same session -- must be excluded (only assistant).
        db.add(
            Message(
                id=new_id("msg"),
                tenant_id="tenant-demo",
                session_id="session-1",
                role="user",
                content="请生成文档",
                metadata_json={
                    "harness_artifacts": [_artifact("task-y", "user-side.md")]
                },
            )
        )
        db.commit()
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {})

    assert result["success"] is True
    assert result["data"] == {"deliverables": [], "count": 0}


def test_list_published_deliverables_rejects_bad_limit(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {"limit": "50"})

    assert result["success"] is False
    assert result["error"]["code"] == "INVALID_ARGUMENTS"


def test_list_published_deliverables_enforces_limit_across_messages(
    tmp_path,
    monkeypatch,
) -> None:
    """limit 是全局上限:3 条消息各 2 个 artifact(6 候选),limit=4 时跨消息截断,
    旧消息的 artifact 不得因外层循环继续而超过 limit。"""
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        for idx in range(3):
            db.add(
                Message(
                    id=new_id("msg"),
                    tenant_id="tenant-demo",
                    session_id="session-1",
                    role="assistant",
                    content=f"第 {idx} 轮产物",
                    metadata_json={
                        "harness_artifacts": [
                            _artifact(f"task-{idx}", f"doc-{idx}-a.md"),
                            _artifact(f"task-{idx}", f"doc-{idx}-b.md"),
                        ]
                    },
                )
            )
        db.commit()
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {"limit": 4})

    assert result["success"] is True
    assert result["data"]["count"] == 4
    paths = sorted(item["path"] for item in result["data"]["deliverables"])
    assert len(set(paths)) == 4


def test_list_published_deliverables_orders_newest_first(
    tmp_path,
    monkeypatch,
) -> None:
    """默认返回最近发布的交付物(created_at 倒序,id 兜底)。"""
    monkeypatch.setenv("ULTRARAG_DATA_DIR", str(tmp_path / "data"))
    engine = _test_engine()
    with Session(engine) as db:
        base = Message(
            id="msg-base",
            tenant_id="tenant-demo",
            session_id="session-1",
            role="assistant",
            content="旧消息",
            created_at=utc_now(),
            metadata_json={
                "harness_artifacts": [_artifact("task-old", "old.md")]
            },
        )
        db.add(base)
        fresh = Message(
            id="msg-fresh",
            tenant_id="tenant-demo",
            session_id="session-1",
            role="assistant",
            content="新消息",
            created_at=utc_now() + timedelta(seconds=5),
            metadata_json={
                "harness_artifacts": [_artifact("task-new", "new.md")]
            },
        )
        db.add(fresh)
        db.commit()
        invoker = _build_invoker(db)
        result = invoker.invoke("list_published_deliverables", {})

    assert result["success"] is True
    paths = [item["path"] for item in result["data"]["deliverables"]]
    assert paths == ["new.md", "old.md"]