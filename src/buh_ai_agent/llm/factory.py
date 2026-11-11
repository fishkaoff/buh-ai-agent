"""Создание Open AI compatible llm provider"""

from langchain_openai import ChatOpenAI

from buh_ai_agent.core.settings import Settings


def create_llm(settings: Settings) -> ChatOpenAI:
    """Инициализирует и создает ChatOpenAI по переданным настройкам
    Args:
        settings: Settings

    Returns: ChatOpenAI
    """

    return ChatOpenAI(
        model=settings.llm_model,
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        temperature=settings.llm_temperature,
        timeout=settings.llm_timeout,
    )
