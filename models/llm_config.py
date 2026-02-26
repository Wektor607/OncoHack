"""
Конфигурация LLM провайдеров.
Измените этот файл для выбора нужной модели.
"""
import os
from .design_recommender import (
    ClaudeProvider,
    OpenAIProvider,
    GroqProvider,
    GeminiProvider,
    OllamaProvider,
    LMStudioProvider,
    YandexGPTProvider,
    MockProvider
)

# ============================================================================
# ПРОВАЙДЕР ДЛЯ ГЕНЕРАЦИИ ОБОСНОВАНИЯ (reasoning)
# Раскомментируйте ОДИН из вариантов ниже
# ============================================================================

# ---- Ollama — локально, без интернета ★ ТЕКУЩИЙ ВЫБОР ----
# Установка: https://ollama.ai
# Рекомендуемые модели:
#   ollama pull qwen2.5:14b   — лучшее качество (~8GB)
#   ollama pull mistral-nemo  — хороший баланс (~4GB)
def get_llm_provider():
    """Основной LLM для анализа данных.
    Управляется переменными окружения из .env:
      LLM_PROVIDER  — провайдер: ollama | groq | gemini | claude | mock
      OLLAMA_MODEL  — модель (для Ollama)
      OLLAMA_BASE_URL — URL сервера Ollama
      GROQ_API_KEY / GEMINI_API_KEY / CLAUDE_API_KEY — ключи для облачных LLM
    """
    provider = os.getenv("LLM_PROVIDER", "ollama").lower()

    if provider == "ollama":
        return OllamaProvider(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        )
    elif provider == "groq":
        return GroqProvider(
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )
    elif provider == "gemini":
        return GeminiProvider(
            api_key=os.getenv("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        )
    elif provider == "claude":
        return ClaudeProvider(
            api_key=os.getenv("CLAUDE_API_KEY"),
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        )
    elif provider == "yandex":
        return YandexGPTProvider(
            api_key=os.getenv("YANDEX_API_KEY"),
            folder_id=os.getenv("YANDEX_FOLDER_ID"),
            model=os.getenv("YANDEX_MODEL", "yandexgpt/latest"),
        )
    elif provider == "mock":
        return MockProvider()
    else:
        raise ValueError(f"Неизвестный LLM_PROVIDER: {provider}")


# ============================================================================
# ПРОВАЙДЕР ДЛЯ ПЕРЕВОДА НА РУССКИЙ ЯЗЫК (translation)
# Раскомментируйте ОДИН из вариантов ниже
# ============================================================================

def get_translate_provider():
    """LLM для перевода обоснования на русский язык.
    Управляется переменными окружения из .env:
      TRANSLATE_PROVIDER — провайдер: groq | gemini | claude | ollama | same
                           "same" — использовать тот же провайдер, что и LLM_PROVIDER
      GROQ_API_KEY / GEMINI_API_KEY / CLAUDE_API_KEY — ключи
    """
    provider = os.getenv("TRANSLATE_PROVIDER", "groq").lower()

    if provider == "same":
        return None  # DesignRecommender использует основной LLM
    elif provider == "groq":
        return GroqProvider(
            api_key=os.getenv("GROQ_API_KEY"),
            model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        )
    elif provider == "gemini":
        return GeminiProvider(
            api_key=os.getenv("GEMINI_API_KEY"),
            model=os.getenv("GEMINI_MODEL", "gemini-2.0-flash"),
        )
    elif provider == "claude":
        return ClaudeProvider(
            api_key=os.getenv("CLAUDE_API_KEY"),
            model=os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"),
        )
    elif provider == "ollama":
        return OllamaProvider(
            model=os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
            base_url=os.getenv("OLLAMA_BASE_URL", "http://ollama:11434"),
        )
    elif provider == "yandex":
        return YandexGPTProvider(
            api_key=os.getenv("YANDEX_API_KEY"),
            folder_id=os.getenv("YANDEX_FOLDER_ID"),
            model=os.getenv("YANDEX_MODEL", "yandexgpt/latest"),
        )
    else:
        raise ValueError(f"Неизвестный TRANSLATE_PROVIDER: {provider}")
