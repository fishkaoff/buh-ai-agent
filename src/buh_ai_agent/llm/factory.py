"""Создание Open AI compatible llm provider"""

from langchain_openai import ChatOpenAI

from buh_ai_agent.core.settings import Settings


def create_llm(settings: Settings) -> ChatOpenAI:
    """Инициализирует и создает ChatOpenAI по переданным настройкам.

    Args:
        settings: Settings

    Returns:
        ChatOpenAI

    Raises:
        ValueError: Если не заданы base_url, api_key или модель —
            конфигурация LLM обязательна для запуска агента.
    """
    base_url = settings.llm_base_url.strip()
    model = settings.llm_model.strip()
    api_key = settings.llm_api_key.get_secret_value()
    if not base_url or not model or not api_key:
        raise ValueError(
            "LLM не настроена: заполните LLM_BASE_URL, LLM_API_KEY и LLM_MODEL "
            "в файле .env (см. .env.example)."
        )
    return ChatOpenAI(
        model=model,
        base_url=base_url,
        api_key=api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
    )
