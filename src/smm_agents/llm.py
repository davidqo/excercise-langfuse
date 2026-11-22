from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_ollama import ChatOllama

from smm_agents.config import ModelConfig


def build_llm(config: ModelConfig) -> BaseChatModel:
    if config.provider != "ollama":
        raise ValueError(
            f"Unsupported provider '{config.provider}'. First version supports only 'ollama'."
        )

    return ChatOllama(
        model=config.model,
        base_url=config.base_url,
        temperature=config.temperature,
    )
