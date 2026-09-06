"""Checks for canonical project documentation and implementation inputs."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN_DIR = ROOT / "artifacts" / "Design TZ для экранов"
DESIGN_HTML = DESIGN_DIR / "Проверка контрагентов v2.dc.html"


def test_canonical_project_documents_exist() -> None:
    """The repository must expose one discoverable implementation entrypoint."""
    expected = (
        ROOT / "AGENTS.md",
        ROOT / "NEXT_STEPS.md",
        ROOT / "README.md",
        ROOT / "docs" / "architecture.md",
        ROOT / "docs" / "SUBAGENT_GUIDE.md",
        ROOT / "docs" / "WORK_PLAN.md",
        ROOT / "docs" / "Specs" / "00_OVERVIEW_AND_INDEX.md",
        ROOT / "docs" / "Specs" / "10_SYSTEM_CONTRACTS.md",
    )

    assert all(path.is_file() for path in expected)


def test_accepted_design_bundle_is_available() -> None:
    """The React implementation must retain access to the accepted baseline."""
    assert DESIGN_HTML.is_file()
    assert (DESIGN_DIR / "support.js").is_file()
    assert (DESIGN_DIR / "icons" / "ATTRIBUTION.md").is_file()


def test_approved_mock_json_is_available() -> None:
    """Data work requires the approved source rather than a replacement fixture."""
    assert (ROOT / "artifacts" / "contractors_audit.snapshot.json").is_file()


def test_work_plan_records_parallel_delivery_boundaries() -> None:
    """Key decisions should remain explicit while the monorepo is scaffolded."""
    plan = (ROOT / "docs" / "WORK_PLAN.md").read_text(encoding="utf-8")

    assert "apps/web" in plan
    assert "services/ui_api" in plan
    assert "services/agent" in plan
    assert "services/mcp" in plan
    assert "Dockerfile" in plan
    assert "compose.yaml" in plan
    assert "scripts/import_reports" in plan
    assert "отдельная sanitized fixture не создаётся" in plan


def test_orchestration_supports_parallel_user_reviewed_waves() -> None:
    """The main agent must delegate work and stop for user-visible checkpoints."""
    agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    next_steps = (ROOT / "NEXT_STEPS.md").read_text(encoding="utf-8")

    assert "единственной точкой общения с\nпользователем" in agents
    assert "передавай субагенту" in agents
    assert "запускай их параллельно" in agents
    assert "checkpoint с пользователем" in agents
    assert "Следующая крупная волна запускается после review" in next_steps
    assert "Последующие MVP-срезы" in next_steps
    assert ".worktrees/<task-id>-<slug>" in agents
    assert "docs/checkpoints/tasks/<TASK_ID>.md" in agents


def test_subagent_work_is_resumable_from_committed_checkpoints() -> None:
    """A stopped task should be recoverable without conversation history."""
    guide = (ROOT / "docs" / "SUBAGENT_GUIDE.md").read_text(encoding="utf-8")

    assert "Не используй stash как checkpoint" in guide
    assert "git log -5 --oneline" in guide
    assert "Следующее действие" in guide
    assert "Last commit" in guide
    assert "оставь task-ветку и worktree в чистом состоянии" in guide
