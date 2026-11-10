# buh-ai-agent

AI-агент для работы с бухгалтерскими операциями в 1С через OData. Сейчас реализован HTTP Core (FastAPI); LangGraph, LLM-интеграция и загрузка Skills будут подключены на следующих этапах.

## Стек

- Python 3.12+
- uv — управление зависимостями и виртуальным окружением
- FastAPI — HTTP-сервер
- Uvicorn — ASGI-сервер
- Pydantic v2 + pydantic-settings — валидация и конфигурация
- pytest + httpx — тестирование
- Ruff — линтер и форматирование

## Структура проекта

```text
src/
└── buh_ai_agent/
    ├── __init__.py
    ├── main.py          # точка входа: запуск uvicorn
    ├── app.py           # фабрика FastAPI-приложения, lifespan
    ├── api/
    │   ├── router.py    # общий API Router
    │   ├── routes/
    │   │   ├── health.py
    │   │   └── chat.py
    │   └── schemas/
    │       └── chat.py
    └── core/
        └── settings.py  # pydantic-settings
tests/
├── unit/
└── integration/
```

Репозиторий также содержит:

- `.opencode/skills/` — Skills для работы с 1С (будут загружаться агентом из Python-приложения)
- `config/onec/` — клиент OData и конфигурация 1С
- `docs/` — документация по возможностям 1С и Skills

## Установка

```bash
uv sync
```

## Запуск HTTP-сервера

```bash
uv run python -m buh_ai_agent.main
```

Сервер слушает `http://127.0.0.1:8000`. Для режима отладки с autoreload создайте `.env` из `.env.example` и выставьте `DEBUG=true`.

## Тесты

```bash
uv run pytest
```

## Линтер и форматирование

```bash
uv run ruff check .
uv run ruff format .
```

## API

| Метод | Путь     | Описание                                        |
|-------|----------|-------------------------------------------------|
| GET   | `/health`| Проверка живости сервиса, возвращает `{"status": "ok"}` |
| POST  | `/chat`  | Сообщение агенту. Пока возвращает `501 Not Implemented` |

Пример:

```bash
curl -s http://127.0.0.1:8000/health
curl -s -X POST http://127.0.0.1:8000/chat -H "Content-Type: application/json" -d '{"message": "Привет, что ты умеешь?"}'
```
