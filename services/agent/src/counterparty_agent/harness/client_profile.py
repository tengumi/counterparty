"""The authorized client the agent is answering for.

Alfa Business knows who is asking: their company, industry, region, role and
the products they use. That context shapes which parts of a counterparty
report matter — a builder taking a supplier prepayment cares about the ability
to deliver and about advance-payment risk. It is only a backdrop: the agent
must not invent balances, turnover or the client's own counterparties from it,
and the terms of a specific deal still come from the dialogue.

One demo client is configured by default; a deployment overrides it with
``AGENT_CLIENT_PROFILE_JSON``.
"""

import json
from dataclasses import dataclass

__all__ = ["DEMO_CLIENT", "ClientProfile", "load_client_profile"]


@dataclass(frozen=True, slots=True)
class ClientProfile:
    """The base context of the signed-in Alfa Business client."""

    company_name: str
    inn: str
    region: str
    industry: str
    business_segment: str
    user_role: str
    products: tuple[str, ...]

    def render(self) -> str:
        """Render the profile as a prompt block."""
        products = ", ".join(self.products) if self.products else "—"
        return "\n".join(
            [
                "## Кто задаёт вопрос (профиль клиента Альфа-Бизнеса)",
                f"- Компания: {self.company_name}, ИНН {self.inn}, {self.region}",
                f"- Отрасль: {self.industry}; сегмент: {self.business_segment}",
                f"- Роль пользователя: {self.user_role}",
                f"- Подключённые продукты: {products}",
                "Это фон: учитывай отрасль, роль и то, что сделки клиента обычно "
                "с предоплатой. Не приписывай клиенту данные сверх этого — его "
                "остатки, обороты и контрагентов ты не знаешь. Сумму, аванс, срок "
                "и предмет конкретной сделки узнавай из диалога.",
            ]
        )


DEMO_CLIENT = ClientProfile(
    company_name="ООО «СтройКонтур»",
    inn="7700000000",
    region="Москва",
    industry="строительство",
    business_segment="малый бизнес",
    user_role="генеральный директор",
    products=("РКО", "Альфа-Про"),
)
"""Default client for the demo test pack (DEMO.md)."""


def load_client_profile(raw: str | None) -> ClientProfile:
    """Parse a JSON override, or return the demo client.

    A malformed or partial override falls back to the demo client rather than
    failing a run: the profile is a backdrop, not a hard input.
    """
    if not raw:
        return DEMO_CLIENT
    try:
        data = json.loads(raw)
        return ClientProfile(
            company_name=str(data["company_name"]),
            inn=str(data["inn"]),
            region=str(data["region"]),
            industry=str(data["industry"]),
            business_segment=str(data["business_segment"]),
            user_role=str(data["user_role"]),
            products=tuple(str(item) for item in data.get("products", ())),
        )
    except (TypeError, ValueError, KeyError):
        return DEMO_CLIENT
