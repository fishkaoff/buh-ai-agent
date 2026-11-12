"""Реестр подключений к базам 1С: выбор базы для Tools агента.

Приложение может работать с несколькими базами 1С (ONEC_DATABASES).
Инструменты агента получают аргумент `database` — имя базы; реестр
сопоставляет имя с клиентом и конфигурацией базы.

Правило выбора (Skill onec-odata, мультибазность):
- имя задано — используется база с этим именем (регистр не важен);
- имя пустое — допустимо только при одной настроенной базе;
- при нескольких базах пустое имя — ошибка со списком баз: агент должен
  уточнить у пользователя, в какой базе работать, а не выбирать молча.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import httpx

from buh_ai_agent.integrations.onec.client import OnecClient
from buh_ai_agent.integrations.onec.config import OnecConnectionConfig
from buh_ai_agent.integrations.onec.errors import OnecError


def _available_databases(configs: Sequence[OnecConnectionConfig]) -> str:
    """Строит список доступных баз для сообщений об ошибках и промпта."""
    parts = [config.database + (f" ({config.label})" if config.label else "") for config in configs]
    return "Доступные базы: " + ("; ".join(parts) if parts else "нет") + "."


def _database_required_error(configs: Sequence[OnecConnectionConfig]) -> str:
    """Ошибка «база не указана» при нескольких подключениях."""
    return (
        "Не указана база 1С (аргумент database). Из запроса не ясно, в какой базе "
        "работать, — уточните у пользователя. " + _available_databases(configs)
    )


class OnecClients:
    """Клиенты 1С по базам: сопоставляет имя базы клиенту и конфигурации."""

    def __init__(
        self,
        configs: Sequence[OnecConnectionConfig],
        clients: Mapping[str, OnecClient],
    ) -> None:
        """Инициализирует реестр готовыми клиентами.

        Args:
            configs: Конфигурации баз (минимум одна).
            clients: Клиенты по имени базы (`config.database`).

        Raises:
            OnecError: Конфигурации нет.
        """
        if not configs:
            raise OnecError("Не настроено ни одного подключения к 1С.")
        self.configs: tuple[OnecConnectionConfig, ...] = tuple(configs)
        self.clients: Mapping[str, OnecClient] = dict(clients)

    @classmethod
    def from_configs(
        cls,
        configs: Sequence[OnecConnectionConfig],
        *,
        timeout: float = 30.0,
        max_retries: int = 1,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> OnecClients:
        """Создаёт реестр, открывая клиент для каждой конфигурации.

        Args:
            configs: Конфигурации баз.
            timeout: Таймаут HTTP-запроса.
            max_retries: Число повторов GET при сетевых ошибках.
            transport: httpx-транспорт (для тестов); None — обычный сетевой.

        Returns:
            Готовый реестр.
        """
        return cls(
            configs,
            {
                config.database: OnecClient.from_config(
                    config,
                    timeout=timeout,
                    max_retries=max_retries,
                    transport=transport,
                )
                for config in configs
            },
        )

    @classmethod
    def single(cls, client: OnecClient, config: OnecConnectionConfig) -> OnecClients:
        """Реестр из одного готового клиента (удобно в тестах).

        Args:
            client: Клиент 1С.
            config: Конфигурация этой базы.

        Returns:
            Реестр с одной базой.
        """
        return cls([config], {config.database: client})

    def resolve(self, database: str = "") -> tuple[OnecClient, OnecConnectionConfig]:
        """Возвращает клиент и конфигурацию выбранной базы.

        Args:
            database: Имя базы из конфигурации; пусто — единственная база.

        Returns:
            Пара (клиент, конфигурация базы).

        Raises:
            OnecError: База не указана при нескольких подключениях или имя
                не найдено среди настроенных баз.
        """
        wanted = database.strip()
        if not wanted:
            if len(self.configs) == 1:
                config = self.configs[0]
                return self.clients[config.database], config
            raise OnecError(_database_required_error(self.configs))
        for config in self.configs:
            if config.database.casefold() == wanted.casefold():
                return self.clients[config.database], config
        raise OnecError(
            f"База 1С «{wanted}» не найдена в конфигурации. " + _available_databases(self.configs)
        )

    def describe(self) -> list[dict[str, str]]:
        """Описывает базы для системного промпта агента.

        Returns:
            Список объектов {name, label} (label может быть пустым).
        """
        return [
            {
                "name": config.database,
                "label": config.label or config.defaults.organization.name,
            }
            for config in self.configs
        ]

    async def aclose(self) -> None:
        """Закрывает HTTP-клиенты всех баз."""
        for client in self.clients.values():
            await client.aclose()
