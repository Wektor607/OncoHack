import requests
from abc import ABC, abstractmethod
from typing import Optional

class LLMProvider(ABC):
    """Абстрактный базовый класс для LLM провайдеров."""

    @abstractmethod
    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        """
        Генерирует ответ от LLM.

        Args:
            prompt: Пользовательский промпт
            system_prompt: Системный промпт (опционально)

        Returns:
            Текстовый ответ от модели
        """
        pass


class ClaudeProvider(LLMProvider):
    """Провайдер для Claude API (Anthropic)."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.anthropic.com/v1/messages"

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        data = {
            "model": self.model,
            "max_tokens": 2048,
            "messages": [{"role": "user", "content": prompt}]
        }

        if system_prompt:
            data["system"] = system_prompt

        response = requests.post(self.base_url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        return result["content"][0]["text"]


class OpenAIProvider(LLMProvider):
    """Провайдер для OpenAI API (GPT-4, GPT-3.5)."""

    def __init__(self, api_key: str, model: str = "gpt-4"):
        self.api_key = api_key
        self.model = model
        self.base_url = "https://api.openai.com/v1/chat/completions"

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048
        }

        response = requests.post(self.base_url, headers=headers, json=data)
        response.raise_for_status()

        result = response.json()
        return result["choices"][0]["message"]["content"]


class OllamaProvider(LLMProvider):
    """Провайдер для локальных моделей через Ollama."""

    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.base_url}/api/generate"

        full_prompt = prompt
        if system_prompt:
            full_prompt = f"{system_prompt}\n\n{prompt}"

        data = {
            "model": self.model,
            "prompt": full_prompt,
            "stream": False
        }

        response = requests.post(url, json=data)
        response.raise_for_status()

        result = response.json()
        return result["response"]


class LMStudioProvider(LLMProvider):
    """Провайдер для LM Studio (локальные модели через OpenAI-совместимый API)."""

    def __init__(self, model: str = "local-model", base_url: str = "http://localhost:1234/v1"):
        self.model = model
        self.base_url = base_url

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        url = f"{self.base_url}/chat/completions"

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        data = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 2048
        }

        response = requests.post(url, json=data)
        response.raise_for_status()

        result = response.json()
        return result["choices"][0]["message"]["content"]


class MockProvider(LLMProvider):
    """Mock провайдер для тестирования без API."""

    def generate(self, prompt: str, system_prompt: Optional[str] = None) -> str:
        # Пытаемся извлечь информацию из промпта
        cv_intra = 25.0  # По умолчанию
        t_half = None

        # Проверяем есть ли CVintra в данных
        if "CVintra:" in prompt:
            import re
            cv_match = re.search(r'CVintra:\s*(\d+\.?\d*)', prompt)
            if cv_match:
                cv_intra = float(cv_match.group(1))
        else:
            # Если нет, используем типичное значение
            cv_intra = 20.0

        # Проверяем T½
        if "T½:" in prompt or "T1/2:" in prompt:
            import re
            t_match = re.search(r'T½:\s*(\d+\.?\d*)', prompt)
            if t_match:
                t_half = float(t_match.group(1))

        # Определяем дизайн на основе найденных данных
        if t_half and t_half > 24:
            design = "Параллельный"
            reasoning = f"Препарат имеет длительный период полувыведения T½ = {t_half} часов (> 24 ч), что делает перекрёстный дизайн непрактичным. Рекомендуется параллельный дизайн."
        elif cv_intra <= 30:
            design = "2×2 Cross-over"
            reasoning = f"На основе типичных значений для данного класса препаратов, CVintra оценивается как {cv_intra}%. Это указывает на низкую вариабельность, для которой подходит стандартный дизайн 2×2 Cross-over."
        elif cv_intra <= 50:
            design = "3-way Replicate"
            reasoning = f"CVintra составляет {cv_intra}%, что указывает на средневариабельный препарат. Рекомендуется дизайн 3-way Replicate с повторными измерениями."
        else:
            design = "4-way Replicate (RSABE)"
            reasoning = f"CVintra составляет {cv_intra}%, что указывает на высоковариабельный препарат. Требуется дизайн 4-way Replicate с применением RSABE."

        return f"""DESIGN: {design}
            N_SUBJECTS: 24
            CV_INTRA: {cv_intra}
            T_HALF: {t_half if t_half else 'N/A'}

            REASONING:
            {reasoning}
            Данная рекомендация основана на анализе фармакокинетических данных и соответствует стандартам FDA/EMA для исследований биоэквивалентности.

            ⚠️ Обратите внимание: Это тестовый режим (MockProvider). Для получения более точных рекомендаций настройте реальную LLM модель в llm_config.py.
            """
