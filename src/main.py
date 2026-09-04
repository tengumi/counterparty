"""Единая точка локального запуска приложения."""

from counterparty_agent.api.routes import run


def main() -> None:
    """Запустить FastAPI с настройками из ``counterparty_agent.config``."""

    run()


if __name__ == "__main__":
    main()
