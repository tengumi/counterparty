"""Регрессии границ проектного чата на синтетическом источнике."""

import json
from types import SimpleNamespace

import pytest
from pydantic import SecretStr
from test_projects import client as project_client
from test_projects import command, create
from test_projects import settings as project_settings

client = project_client
settings = project_settings


class TopicSelector:
    async def close(self):
        pass

    def __init__(self, topic):
        self.topic = topic
        self.chat = SimpleNamespace(completions=self)
        self.calls = 0

    async def create(self, **kwargs):
        self.calls += 1
        message = next(
            m["content"]
            for m in kwargs["messages"]
            if m["role"] == "user" and "<INPUT_DATA>" in m["content"]
        )
        data = json.loads(message.split("<INPUT_DATA>\n")[1].split("\n</INPUT_DATA>")[0])
        topics = {"report_age", "report_future"} if self.topic == "report_age" else {self.topic}
        chosen = next(f for f in data["approved_facts"] if f["topic"] in topics)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps({"status": "answered", "fact_ids": [chosen["fact_id"]]})
                    ),
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
    assert transport.calls == 1
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
