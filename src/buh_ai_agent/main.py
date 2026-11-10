"""Точка входа: запуск uvicorn-сервера."""

import uvicorn

from buh_ai_agent.core.settings import get_settings


def main() -> None:
    """Запускает HTTP-сервер."""
    settings = get_settings()
    uvicorn.run(
        "buh_ai_agent.app:create_app",
        factory=True,
        host="127.0.0.1",
        port=8000,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
