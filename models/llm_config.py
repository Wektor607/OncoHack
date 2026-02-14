"""
Конфигурация LLM провайдеров.
Измените этот файл для выбора нужной модели.
"""

from .design_recommender import (
    ClaudeProvider,
    OpenAIProvider,
    OllamaProvider,
    LMStudioProvider,
    MockProvider
)


# ============================================================================
# ВЫБЕРИТЕ ПРОВАЙДЕР (раскомментируйте нужный)
# ============================================================================

# ---- 1. Claude (Anthropic) - Лучшее качество ----
# def get_llm_provider():
#     """
#     Использует Claude API для анализа данных.

#     Чтобы настроить:
#     1. Получите API ключ: https://console.anthropic.com/
#     2. Замените "YOUR_API_KEY_HERE" на ваш ключ
#     """
#     return ClaudeProvider(
#         api_key="YOUR_API_KEY_HERE",  # ← ВСТАВЬТЕ ВАШ API КЛЮЧ СЮДА
#         model="claude-sonnet-4-20250514"  # или "claude-opus-4-20250514" для лучшего качества
#     )


# ---- 2. OpenAI (GPT-4) - Хорошее качество ----
# def get_llm_provider():
#     return OpenAIProvider(
#         api_key="your-openai-api-key-here",
#         model="gpt-4"  # или "gpt-3.5-turbo" (дешевле)
#     )


# ---- 3. Ollama - Локальные open-source модели (БЕСПЛАТНО!) ----
# Требуется установка: https://ollama.ai
# Затем: ollama pull llama3 (или другая модель)

def get_llm_provider():
    return OllamaProvider(
        model="mistral",  # или "mistral", "mixtral", "phi"
        base_url="http://localhost:11434"
    )


# ---- 4. LM Studio - Локальные модели с GUI ----
# Скачайте: https://lmstudio.ai
# Запустите сервер в LM Studio (Local Server)
#
# def get_llm_provider():
#     return LMStudioProvider(
#         model="local-model",  # имя модели в LM Studio
#         base_url="http://localhost:1234/v1"
#     )


# ---- 5. Mock - Для тестирования без API ----
# def get_llm_provider():
#     """Возвращает mock провайдер для тестирования."""
#     print("⚠️  Используется MockProvider (тестовый режим)")
#     print("💡 Для реальных результатов настройте провайдер в llm_config.py\n")
#     return MockProvider()


# ============================================================================
# ИНСТРУКЦИИ ПО НАСТРОЙКЕ
# ============================================================================

"""
🔧 КАК НАСТРОИТЬ:

1. Раскомментируйте нужный провайдер выше
2. Закомментируйте MockProvider (текущий по умолчанию)
3. Добавьте API ключ (если нужен)

📝 ПРИМЕРЫ:

A) Использовать Claude:
   - Получите API ключ: https://console.anthropic.com/
   - Раскомментируйте секцию "1. Claude"
   - Вставьте ваш api_key

B) Использовать Ollama (бесплатно, локально):
   - Установите: curl -fsSL https://ollama.ai/install.sh | sh
   - Скачайте модель: ollama pull llama3
   - Раскомментируйте секцию "3. Ollama"

C) Использовать LM Studio (бесплатно, с GUI):
   - Скачайте: https://lmstudio.ai
   - Загрузите модель в LM Studio
   - Запустите Local Server в LM Studio
   - Раскомментируйте секцию "4. LM Studio"

🌟 РЕКОМЕНДУЕМЫЕ OPEN-SOURCE МОДЕЛИ для Ollama:

- llama3 (Meta) - Универсальная, хорошее качество
- mistral (Mistral AI) - Быстрая, эффективная
- mixtral (Mistral AI) - Более мощная версия Mistral
- phi (Microsoft) - Компактная, быстрая
- qwen (Alibaba) - Хорошо работает с медицинскими данными

Установка моделей:
  ollama pull llama3
  ollama pull mistral
  ollama pull mixtral

Запуск Ollama сервера:
  ollama serve

💰 СТОИМОСТЬ API:

Claude API:
  - Sonnet: ~$3 за 1M input токенов
  - Opus: ~$15 за 1M input токенов

OpenAI:
  - GPT-4: ~$30 за 1M input токенов
  - GPT-3.5: ~$0.5 за 1M input токенов

Ollama/LM Studio:
  - БЕСПЛАТНО (работает локально)
"""
