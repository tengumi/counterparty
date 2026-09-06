"""Регрессии границ проектного чата на синтетическом источнике."""

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from test_projects import client as project_client
from test_projects import command, create
from test_projects import settings as project_settings
from test_review_agent import ReviewModel

from counterparty_agent.ai.deal import DealContext, DealPatch, apply_deal, deal_facts
from counterparty_agent.ai.reasoning import ReviewDraft
from counterparty_agent.ai.router import IntentPlan, RouterResult
from counterparty_agent.projects.evidence import question_facts
from counterparty_agent.projects.models import Project
from counterparty_agent.projects.planning import accept_user_context, remember_question

client = project_client
settings = project_settings


def test_late_condition_closes_its_open_question_after_another_field_cleared_pending():
    project = Project(
        project_id="late-answer",
        title="Проверка позднего ответа",
        session_id="isolated",
        source_hash="unit-test",
        deal=apply_deal(DealContext(), DealPatch(goal="выбор поставщика"), "выбор поставщика"),
    )
    project.deal.question = "Какова сумма сделки?"
    project.deal.asked_fields = ["amount"]
    remember_question(project, project.deal.question)
    question = project.questions[0]
    accept_user_context(
        project,
        apply_deal(project.deal, DealPatch(advance="аванс 80%"), "Планируем аванс 80%."),
        "Планируем аванс 80%.",
    )
    assert project.deal.question is None and question.status == "open"
    payment_id = project.deal.terms["advance"].evidence_id

    answer = "Сумма сделки — 100 рублей."
    accept_user_context(
        project, apply_deal(project.deal, DealPatch(amount="100 рублей"), answer), answer
    )
    assert question.status == "answered" and question.answer == answer
    assert question.answered_at is not None and question.evidence_ids
    assert project.deal.amount == "100 рублей" and project.deal.advance == "аванс 80%"
    assert project.deal.terms["advance"].evidence_id == payment_id
    facts = question_facts(project)
    assert len(facts) == 1 and facts[0].claim.evidence_ids == tuple(question.evidence_ids)
    assert answer in facts[0].claim.text and "Планируем аванс" not in facts[0].claim.text
    assert {fact.metric for fact in deal_facts(project.deal)} == {"goal", "advance", "amount"}


class TopicSelector:
    async def close(self):
        pass

    def __init__(self, topic):
        self.topic = topic
        self.chat = SimpleNamespace(completions=self)
        self.calls = 0
        self.operations = []

    async def create(self, **kwargs):
        self.calls += 1
        message = next(
            m["content"]
            for m in kwargs["messages"]
            if m["role"] == "user" and "<INPUT_DATA>" in m["content"]
        )
        data = json.loads(message.split("<INPUT_DATA>\n")[1].split("\n</INPUT_DATA>")[0])
        if "session" in data:
            self.operations.append("route")
            content = {"action": "ask", "scope": "group", "targets": []}
        elif "blocks" in data:
            self.operations.append("verify")
            content = {"unsupported_blocks": [], "answers_question": True}
        elif "available_topics" in data:
            self.operations.append("decide")
            topic = {
                "report_age": "data_quality",
                "comparison_loss": "finance",
                "user_document": "documents",
            }.get(self.topic, "company")
            content = (
                {"action": "finish", "topics": []}
                if topic in data["read_topics"]
                else {"action": "read", "topics": [topic]}
            )
        elif "approved_facts" in data:
            self.operations.append("synthesize")
            topics = {"report_age", "report_future"} if self.topic == "report_age" else {self.topic}
            if self.topic == "comparison_loss":
                chosen = next(f for f in data["approved_facts"] if f["metric"] == "financial_loss")
            else:
                chosen = next(f for f in data["approved_facts"] if f["topic"] in topics)
            content = {
                "blocks": [
                    {"kind": "fact", "text": chosen["text"], "fact_ids": [chosen["fact_id"]]}
                ]
            }
        else:
            self.operations.append("extract")
            content = {}
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(content)),
                    finish_reason="stop",
                )
            ]
        )


class DealReviewer(TopicSelector):
    """Изолированный транспорт: читает финансы, затем договор и проверяет общий вывод."""

    def __init__(self, *, clarify=False):
        super().__init__("mixed")
        self.clarify = clarify
        self.contexts = []

    async def create(self, **kwargs):
        self.calls += 1
        message = next(
            item["content"]
            for item in kwargs["messages"]
            if item["role"] == "user" and "<INPUT_DATA>" in item["content"]
        )
        data = json.loads(message.split("<INPUT_DATA>\n")[1].split("\n</INPUT_DATA>")[0])
        question = message.split("<QUESTION>\n")[1].split("\n</QUESTION>")[0]
        self.contexts.append(data)
        if "session" in data:
            self.operations.append("route")
            content = {
                "action": "ask",
                "scope": "group",
                "targets": [],
                "deal_patch": {"advance": "оплата после поставки"}
                if "оплата после поставки" in question
                else {"advance": "аванс 20 процентов"}
                if "аванс 20 процентов" in question
                else {},
            }
        elif "blocks" in data:
            self.operations.append("verify")
            content = {"unsupported_blocks": [], "answers_question": True}
        elif "available_topics" in data:
            self.operations.append("decide")
            if self.clarify and "advance" in data["missing_fields"]:
                content = {
                    "action": "ask",
                    "topics": [],
                    "question_field": "advance",
                    "question": "Какие условия оплаты согласованы?",
                }
            elif "finance" not in data["read_topics"]:
                content = {"action": "read", "topics": ["finance"]}
            elif "documents" in data["available_topics"]:
                assert any(f["metric"] == "financial_loss" for f in data["approved_facts"])
                content = {"action": "read", "topics": ["documents"]}
            else:
                content = {"action": "finish", "topics": []}
        elif "approved_facts" in data:
            self.operations.append("synthesize")
            loss = next(f for f in data["approved_facts"] if f["metric"] == "financial_loss")
            source = next(
                (f for f in data["approved_facts"] if f["topic"] == "user_document"), loss
            )
            blocks = [{"kind": "fact", "text": loss["text"], "fact_ids": [loss["fact_id"]]}]
            if source != loss:
                document_ids = [source["fact_id"]]
                document_text = source["text"]
                if "current_terms" in data.get("answer_requirements", []):
                    condition = next(
                        f
                        for f in data["approved_facts"]
                        if f["topic"] == "deal_context" and f["metric"] == "advance"
                    )
                    document_ids.append(condition["fact_id"])
                    document_text = (
                        f"{source['text']} {condition['text']} "
                        "Эти условия расходятся и требуют согласования до подписания."
                    )
                blocks.append(
                    {
                        "kind": "interpretation",
                        "text": document_text,
                        "fact_ids": document_ids,
                    }
                )
            content = {"blocks": blocks}
        else:
            self.operations.append("extract")
            content = (
                {"advance": "оплата после поставки"} if "оплата после поставки" in question else {}
            )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(content)),
                    finish_reason="stop",
                )
            ]
        )


def install(client, topic):
    runtime = client.app.state.runtime
    runtime.settings.llm_api_key = SecretStr("synthetic")
    transport = TopicSelector(topic)
    runtime.llm_client = transport
    return transport


def ask(client, project, question):
    return client.post(
        f"/api/projects/{project['project_id']}/ask",
        json={
            "expected_revision": project["revision"],
            "question": question,
        },
    )


def test_project_focus_survives_reload_and_pronoun_then_returns_to_group(client, monkeypatch):
    project = create(client)
    selected = project["snapshot_ids"][1]
    install(client, "report_age")
    model = ReviewModel(monkeypatch)
    route_focus = []

    async def route(settings, question, data, *, client):
        route_focus.append(data["focused_position"])
        return RouterResult(
            IntentPlan(
                action="ask",
                position=2 if "второго" in question else None,
                # Последний scope намеренно ошибочен: явную групповую фразу
                # обязан применить сервер, а не вероятностный маршрутизатор.
                scope="current",
                answer_mode="analysis",
            ),
            "routed",
            True,
            "unit-only",
        )

    monkeypatch.setattr("counterparty_agent.projects.dialogue.route_intent", route)
    for index, text in enumerate(
        (
            "Какие риски у второго?",
            "А какие у него риски?",
            "Нужна общая проверка доступных отчётов.",
        )
    ):
        data = ask(client, project, text).json()
        assert data["status"] == "answered"
        project = data["project"]
        assert project["focused_snapshot_id"] == (selected if index < 2 else None)
        restored = client.get(f"/api/projects/{project['project_id']}").json()
        assert restored["focused_snapshot_id"] == project["focused_snapshot_id"]
        project = restored
    assert route_focus == [2, 2, 2]
    assert [
        sum(
            fact["topic"] == "bank_signal" and fact["metric"] is None
            for fact in data["approved_facts"]
        )
        for data in model.inputs(ReviewDraft)
    ] == [1, 1, len(project["snapshot_ids"])]


def test_focus_command_is_scoped_revisioned_and_cleared_when_excluded(client):
    project = create(client)
    transport = install(client, "report_age")
    selected = project["snapshot_ids"][1]
    previous_revision = project["revision"]
    project = command(client, project, "set_focus", value=selected)
    assert project["focused_snapshot_id"] == selected and transport.calls == 0
    endpoint = f"/api/projects/{project['project_id']}/commands"
    assert (
        client.post(
            endpoint,
            json={"action": "set_focus", "expected_revision": previous_revision, "value": ""},
        ).status_code
        == 409
    )
    assert (
        client.post(
            endpoint,
            json={
                "action": "set_focus",
                "expected_revision": project["revision"],
                "value": "outside",
            },
        ).status_code
        == 422
    )
    project = command(client, project, "set_focus", value="")
    assert project["focused_snapshot_id"] is None
    project = command(client, project, "set_focus", value=selected)
    project = command(client, project, "set_shortlist", snapshot_ids=project["snapshot_ids"][:1])
    assert project["focused_snapshot_id"] is None and transport.calls == 0
    assert (
        client.post(
            endpoint,
            json={
                "action": "set_focus",
                "expected_revision": project["revision"],
                "value": selected,
            },
        ).status_code
        == 422
    )


def test_report_age_uses_one_analysis_clock_before_saving(client):
    project = create(client)
    project = command(client, project, "set_shortlist", snapshot_ids=project["snapshot_ids"][:1])
    project = command(client, project, "run")
    transport = install(client, "report_age")
    response = ask(client, project, "Насколько старый отчёт?")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered" and data["evidence"]
    assert data["project"]["revision"] == project["revision"] + 1
    assert transport.operations == ["route", "decide", "decide", "synthesize", "verify"]
    accepted = command(
        client, data["project"], "accept_memo", proposal_id=project["proposal"]["proposal_id"]
    )
    assert accepted["memo"] and accepted["proposal"] is None


@pytest.mark.parametrize(
    "question",
    [
        "Какой светофор ИНН 123?",
        "Какой светофор «Несуществующая компания»?",
        "Какая выручка за первый квартал 2025?",
        "Какая выручка за 2022 год?",
    ],
)
def test_wrong_entity_and_unsupported_period_do_not_use_old_group(client, question):
    project = create(client)
    transport = install(client, "comparison_bank_signal")
    response = ask(client, project, question)
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "insufficient_data" and not data["claims"]
    assert data["project"]["revision"] == project["revision"]
    assert transport.calls == 0


def test_long_document_does_not_block_reports_and_quotes_are_scoped(client):
    project = create(client)
    text = "Общие сведения. " * 2300 + "Аванс по договору составляет 20 процентов."
    response = client.post(
        f"/api/projects/{project['project_id']}/documents",
        params={
            "expected_revision": project["revision"],
            "name": "договор.txt",
        },
        content=text.encode(),
    )
    assert response.status_code == 201, response.text
    project = response.json()
    install(client, "comparison_loss")
    data = ask(client, project, "У кого есть убыток?").json()
    assert data["status"] == "answered"
    assert all(e["quality"] != "user_document" for e in data["evidence"])
    project = data["project"]
    install(client, "user_document")
    data = ask(client, project, "Какой аванс указан в договоре?").json()
    assert data["status"] == "answered" and "20 процентов" in data["answer"]
    assert "не весь документ" in data["answer"]
    assert all(e["quality"] == "user_document" for e in data["evidence"])


def test_project_analysis_combines_report_with_relevant_document_fragment(client):
    project = create(client)
    text = "Общие сведения. " * 2300 + "Аванс по договору составляет 20 процентов."
    project = client.post(
        f"/api/projects/{project['project_id']}/documents",
        params={"expected_revision": project["revision"], "name": "условия.txt"},
        content=text.encode(),
    ).json()
    install(client, "user_document")
    reviewer = DealReviewer()
    client.app.state.runtime.llm_client = reviewer
    response = ask(client, project, "Какие риски при авансе по договору и убытке в отчёте?")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "answered"
    assert any(source["quality"] == "user_document" for source in data["evidence"])
    assert any(source["quality"] != "user_document" for source in data["evidence"])
    assert len(data["review"]["steps"]) == 3
    assert reviewer.operations == ["route", "decide", "decide", "synthesize", "verify"]
    synthesis = next(
        data for data in reviewer.contexts if "coverage" in data and "approved_facts" in data
    )
    assert any("20 процентов" in f["text"] for f in synthesis["approved_facts"])
    assert synthesis["current_deal"]["goal"] == "Поставка с авансом"


def test_changed_terms_are_persisted_and_invalidate_only_unaccepted_memo(client):
    project = command(client, create(client), "run")
    project = command(
        client, project, "accept_memo", proposal_id=project["proposal"]["proposal_id"]
    )
    accepted = project["memo"]
    project = command(client, project, "run")
    old_proposal = project["proposal"]["proposal_id"]
    install(client, "report_age")
    reviewer = DealReviewer()
    client.app.state.runtime.llm_client = reviewer
    data = ask(client, project, "Теперь условия: оплата после поставки.").json()
    assert data["status"] == "answered"
    assert data["project"]["deal"]["advance"] == "оплата после поставки"
    assert data["project"]["proposal"] is None
    assert data["project"]["memo"] == accepted
    assert data["project"]["memo_stale"] is True
    reopened = client.get(f"/api/projects/{project['project_id']}").json()
    assert reopened["deal"] == data["project"]["deal"]
    assert (
        client.post(
            f"/api/projects/{project['project_id']}/commands",
            json={
                "action": "accept_memo",
                "expected_revision": reopened["revision"],
                "proposal_id": old_proposal,
            },
        ).status_code
        == 409
    )


def test_agent_question_and_explicit_answer_survive_project_reload(client):
    project = create(client)
    install(client, "report_age")
    reviewer = DealReviewer(clarify=True)
    client.app.state.runtime.llm_client = reviewer
    data = ask(client, project, "Помоги оценить условия сделки.").json()
    assert data["status"] == "insufficient_data"
    assert data["project"]["revision"] == project["revision"] + 1
    project = data["project"]
    pending = project["questions"][-1]
    assert pending["status"] == "open" and pending["answer"] is None
    project = command(
        client,
        project,
        "answer_question",
        question_id=pending["question_id"],
        value="Согласована оплата после поставки",
    )
    answered = project["questions"][-1]
    assert answered["status"] == "answered"
    assert answered["answer"] == "Согласована оплата после поставки"
    assert answered["evidence_ids"] and answered["answered_at"]
    assert project["deal"]["advance"] == "оплата после поставки"
    assert project["memo"] is None and project["proposal"] is None
    assert (
        client.get(f"/api/projects/{project['project_id']}").json()["questions"]
        == project["questions"]
    )


def test_plain_chat_reply_answers_the_pending_question_without_reasking(client):
    project = create(client)
    install(client, "report_age")
    reviewer = DealReviewer(clarify=True)
    client.app.state.runtime.llm_client = reviewer
    first = ask(client, project, "Помоги оценить условия сделки.").json()
    assert first["review"]["question"] == (
        "Какие условия оплаты планируются: аванс, оплата после исполнения или поэтапно?"
    )
    data = ask(client, first["project"], "Согласована оплата после поставки.").json()
    assert data["status"] == "answered"
    assert data["review"]["question"] is None
    assert data["project"]["deal"]["advance"] == "оплата после поставки"
    question = data["project"]["questions"][-1]
    assert question["status"] == "answered"
    assert question["answer"] == "Согласована оплата после поставки."
    assert question["evidence_ids"]
    assert reviewer.operations.count("synthesize") == 1


def test_project_run_uses_adaptive_review_and_keeps_proposal_separate(client):
    project = create(client)
    project = client.post(
        f"/api/projects/{project['project_id']}/documents",
        params={"expected_revision": project["revision"], "name": "условия.txt"},
        content="Аванс составляет 20 процентов.".encode(),
    ).json()
    install(client, "report_age")
    reviewer = DealReviewer()
    client.app.state.runtime.llm_client = reviewer
    project = command(client, project, "run")
    assert project["plan_mode"] == "ai"
    assert len(project["plan"]) == 3
    assert reviewer.operations == ["decide", "decide", "decide", "synthesize", "verify"]
    assert project["memo"] is None and project["proposal"] is not None
    assert any(item["kind"] == "analysis" for item in project["proposal"]["memo"]["items"])
    assert project["proposal"]["memo"]["context_hash"]
    project = command(
        client, project, "accept_memo", proposal_id=project["proposal"]["proposal_id"]
    )
    assert project["memo"] and project["memo_stale"] is False


def test_new_terms_replace_the_previous_answer_in_current_evidence(client):
    project = create(client)
    install(client, "report_age")
    reviewer = DealReviewer(clarify=True)
    client.app.state.runtime.llm_client = reviewer
    asked = ask(client, project, "Помоги оценить условия сделки.").json()
    first = ask(client, asked["project"], "Согласован аванс 20 процентов.").json()
    assert first["status"] == "answered"
    assert first["project"]["questions"][-1]["field"] == "advance"
    old_id = first["project"]["questions"][-1]["evidence_ids"][0]
    changed = ask(client, first["project"], "Теперь оплата после поставки.").json()
    assert changed["status"] == "answered"
    latest = changed["project"]["questions"][-1]
    assert latest["answer"] == "Теперь оплата после поставки."
    assert latest["evidence_ids"] != [old_id]
    synthesis = [
        data for data in reviewer.contexts if "coverage" in data and "approved_facts" in data
    ][-1]
    assert not any("аванс 20 процентов" in fact["text"] for fact in synthesis["approved_facts"])


def test_compare_document_conditions_is_not_an_invented_company_name(client):
    project = create(client)
    project = client.post(
        f"/api/projects/{project['project_id']}/documents",
        params={"expected_revision": project["revision"], "name": "условия.txt"},
        content="Проект условий: аванс 20 процентов, срок поставки согласуется.".encode(),
    ).json()
    install(client, "report_age")
    reviewer = DealReviewer()
    client.app.state.runtime.llm_client = reviewer
    result = ask(
        client,
        project,
        "Сопоставь условия проекта договора с нашей постоплатой и отчётами компаний. "
        "Где есть расхождения и что проверить до подписания? Условия пока не меняем.",
    ).json()
    assert result["status"] == "answered" and reviewer.operations[0] == "route"
    synth = next(
        data
        for data in reviewer.contexts
        if "coverage" in data and "approved_facts" in data and "blocks" not in data
    )
    assert {"attention_signal", "user_document"} <= {
        fact["topic"] for fact in synth["approved_facts"]
    }
    assert result["project"]["snapshot_ids"] == project["snapshot_ids"]


def test_offline_question_counts_when_model_is_enabled_later(client):
    project = command(client, create(client), "run")
    assert "advance" in project["deal"]["asked_fields"]
    before = len(project["questions"])
    install(client, "report_age")
    reviewer = DealReviewer(clarify=True)
    client.app.state.runtime.llm_client = reviewer
    result = ask(client, project, "Продолжим анализ условий сделки.").json()
    assert result["status"] == "answered"
    assert len(result["project"]["questions"]) == before
    decisions = [data for data in reviewer.contexts if "missing_fields" in data]
    assert decisions and all("advance" not in data["missing_fields"] for data in decisions)
