# buh-ai-agent

AI-агент для работы с бухгалтерскими операциями в 1С через OData.

Пользователь отправляет запрос на естественном языке (например, «Создай счёт на услуги для ООО Ромашка на 100 000 рублей, НДС 5%»), агент анализирует задачу, определяет необходимый Skill, загружает его инструкцию и выполняет последовательность операций через зарегистрированные Tools и OData 1С.

## Стек

- Python 3.12+
- uv — управление зависимостями и виртуальным окружением
- FastAPI — HTTP-сервер
- Uvicorn — ASGI-сервер
- LangGraph + LangChain — агентский цикл (ReAct с tool-calling)
- LangChain OpenAI — LLM-провайдер (OpenAI-compatible)
- Pydantic v2 + pydantic-settings — валидация и конфигурация
- SQLite — история диалогов и операции (переживают перезапуски)
- pytest + httpx — тестирование
- Ruff — линтер и форматирование

## Структура проекта

```text
src/buh_ai_agent/
├── main.py              # точка входа: запуск uvicorn
├── app.py               # фабрика FastAPI-приложения, lifespan
├── api/
│   ├── router.py        # общий API Router
│   ├── routes/          # health, chat, operations
│   └── schemas/         # Pydantic-схемы запросов/ответов
├── agent/
│   ├── graph.py         # сборка и компиляция графа агента
│   ├── state.py         # состояние графа
│   ├── service.py       # AgentService: история, контекст операций
│   ├── history.py       # сериализация истории, лимит контекста
│   ├── context.py       # диалоговый контекст (ContextVar)
│   ├── prompt.py        # системный промпт
│   └── nodes/chat.py    # узел чата: LLM + tool-calling
├── llm/factory.py       # фабрика LLM (ChatOpenAI)
├── skills/              # загрузка и реестр Skills (.opencode/skills/)
├── tools/               # типизированные Tools (обёртки над сервисами)
│   ├── base.py          # ToolResult: единый формат ответа для агента
│   ├── onec.py          # инструменты 1С (контрагенты, договоры, счета, УПД)
│   └── operations.py    # инструменты операций (create/complete)
├── services/            # бизнес-логика над OData-клиентом 1С
│   ├── counterparties.py, contracts.py, nomenclature.py
│   ├── invoices.py, realizations.py, factures.py
│   ├── reference.py, vat.py, print_forms.py
├── integrations/onec/   # OData-клиент 1С (transport, config, errors, metadata)
├── operations/          # операции агента (processing → awaiting_confirmation → …)
│   ├── models.py        # Operation, OperationDocument, OperationStatus
│   ├── store.py         # OperationStore (протокол) + InMemoryOperationStore
│   └── service.py       # OperationService (машина состояний, подтверждение)
├── storage/
│   └── sqlite.py        # SQLite-хранилище: история диалогов и операции
└── core/settings.py     # pydantic-settings
tests/
├── unit/                # юнит-тесты (клиент, сервисы, tools, agent, operations)
└── integration/         # интеграционные тесты HTTP API
```

Репозиторий также содержит:

- `.opencode/skills/` — Skills для работы с 1С (инструкции для агента, загружаются лениво)
- `config/onec/` — клиент OData и конфигурация 1С
- `docs/` — документация по возможностям 1С и Skills

## Установка

```bash
uv sync
```

Создайте `.env` из `.env.example` и заполните параметры LLM и 1С:

```bash
cp .env.example .env
```

## Запуск HTTP-сервера

```bash
uv run python -m buh_ai_agent.main
```

Сервер слушает `http://127.0.0.1:8000`. Для режима отладки с autoreload выставьте `DEBUG=true` в `.env`.

## Тесты

```bash
uv run pytest
```

## Линтер и форматирование

```bash
uv run ruff check .
uv run ruff format .
```

## Конфигурация

- `.env` — параметры LLM (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) и общие настройки.
- `STORAGE_SQLITE_PATH` — путь к SQLite-базе (по умолчанию `data/agent.db`).
- `AGENT_HISTORY_MESSAGES` — сколько последних сообщений диалога (включая результаты Tools) передаётся LLM.
- `config/onec-config.json` — параметры подключения к 1С (OData URL, учётные данные, дефолты: организация, валюта, ставка НДС). Секреты можно переопределить переменными окружения `ODATA_BASE_URL`, `ODATA_USERNAME`, `ODATA_PASSWORD`, `ONEC_DATABASE`.

## API

| Метод | Путь                                    | Описание                                                                   |
|-------|-----------------------------------------|----------------------------------------------------------------------------|
| GET   | `/health`                               | Проверка живости сервиса, возвращает `{"status": "ok"}`                    |
| POST  | `/chat`                                 | Сообщение агенту с `chat_id` и `user_id`; возвращает ответ и операцию       |
| POST  | `/operations/{operation_id}/confirm`    | Подтверждение операции (`awaiting_confirmation` → `confirmed`)              |
| POST  | `/operations/{operation_id}/reject`     | Отклонение операции (`awaiting_confirmation` → `rejected`)                  |

Пример:

```bash
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" \
  -d '{"chat_id": "123456789", "user_id": "987654321", "message": "Создай счёт на услуги для ООО Ромашка на 100000 рублей, НДС 5%. Услуги: разработка программного обеспечения"}'
curl -s -X POST http://127.0.0.1:8000/operations/{operation_id}/confirm -H "Content-Type: application/json" \
  -d '{"chat_id": "123456789"}'
```

## Последовательный диалог и операции

- **Идентификация диалога.** Telegram Adapter передаёт `chat_id`, `user_id` и `message`. Диалог идентифицируется `chat_id`: история и операции одного чата не смешиваются с другими.
- **История.** Сообщения пользователя, ответы агента и результаты Tools сохраняются в SQLite и восстанавливаются в контекст следующего сообщения. Размер контекста ограничен `AGENT_HISTORY_MESSAGES` (последние N сообщений); обрезка сохраняет целостность tool-потока.
- **Операции.** Любая задача создания документов оформляется операцией (`create_operation` → документы через Tools 1С → `complete_operation`). Операция содержит `chat_id`, `user_id`, `organization_id`, `database_id`, исходный запрос, созданные документы (Ref_Key и номера), результат и даты. Статусы: `processing`, `awaiting_confirmation`, `confirmed`, `rejected`, `failed`.
- **Продолжение.** Активные операции диалога передаются агенту в системном сообщении: продолжение («добавь ещё позицию») работает с той же операцией, без создания новых документов. Если активных операций несколько и непонятно, о какой речь, — агент задаёт уточняющий вопрос.
- **Подтверждение и отклонение.** Проверяется принадлежность операции чату (403), статус (409), существование (404). Повторное подтверждение/отклонение запрещены. На этом этапе подтверждение только меняет состояние — отправка по ЭДО не реализована.

## Ограничения MVP

- Печатные формы (счёт, УПД) формируются как черновики (Markdown/HTML) — официальная печатная форма доступна только из 1С.
- Интеграции Telegram и ЭДО вынесены на следующие этапы (интерфейсы будут отдельными компонентами); подтверждение операции не отправляет документы по ЭДО.
- Реальное подключение к 1С требует доступности OData-сервиса и корректных учётных данных в `config/onec-config.json` или переменных окружения.
- Изменение уже созданных документов 1С (например, добавление позиции в существующий счёт) выполняется агентом только для неподтверждённых операций и учитывает список созданных документов из операции.
