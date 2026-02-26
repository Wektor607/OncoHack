# 🔬 OncoHack — Система разработки дизайна исследований биоэквивалентности

Автоматизированная система для разработки протоколов исследований биоэквивалентности: извлечение фармакокинетических параметров из научных баз данных и генерация синопсиса протокола в формате Word.

> **LLM-движок:** [Yandex Cloud Foundation Models (YandexGPT)](https://yandex.cloud/ru/services/foundation-models) — облачная AI-платформа от Яндекса, обеспечивающая высокое качество работы с русскоязычными медицинскими текстами.

---

## 📋 Возможности

- ✅ Извлечение ФК-данных из **PubMed** и **OpenFDA**
- ✅ Параметры: Cmax, Tmax, AUC, T½, Clearance, CVintra
- ✅ **LLM-рекомендация дизайна** исследования (2×2, 3-way, 4-way, Параллельный)
- ✅ **Автоматический расчёт размера выборки** по стандартам FDA/EMA/ЕАЭС
- ✅ **Генерация синопсиса** протокола в формате `.docx` по официальному шаблону
- ✅ **Веб-интерфейс** с просмотром прогресса в реальном времени (SSE)
- ✅ Поддержка нескольких LLM-провайдеров (Yandex Cloud, Groq, Gemini, Claude)

---

## 🚀 Быстрый старт (Docker)

### 1. Клонировать репозиторий

```bash
git clone <repo-url>
cd OncoHack
```

### 2. Настроить переменные окружения

```bash
cp .env.example .env
```

Заполнить в `.env`:

```env
LLM_PROVIDER=yandex
YANDEX_API_KEY=<ваш API-ключ>
YANDEX_FOLDER_ID=<ваш Folder ID>
YANDEX_MODEL=yandexgpt/latest
TRANSLATE_PROVIDER=same
```

### 3. Запустить

```bash
docker-compose up --build
```

После запуска:

- **Фронтенд:** http://localhost:3000
- **API (Swagger):** http://localhost:8000/docs



---

## ☁️ Yandex Cloud Foundation Models

Проект использует **Yandex Cloud AI Studio** — платформу от Яндекса для работы с большими языковыми моделями.

### Подключение:

1. Зарегистрируйтесь: https://console.yandex.cloud
2. Создайте сервисный аккаунт: **IAM → Сервисные аккаунты → Создать**
3. Назначьте роль `ai.languageModels.user` на каталог
4. Создайте API-ключ: вкладка **API-ключи → Создать новый ключ**
5. Скопируйте **Folder ID** с главной страницы консоли

### Доступные модели:

| Модель              | Качество                                | Цена за 1K токенов |
| ------------------------- | ----------------------------------------------- | ------------------------------- |
| `yandexgpt-lite/latest` | базовое                                  | ~0.20 ₽                        |
| `yandexgpt/latest`      | высокое ★                               | ~1.20 ₽                        |
| `yandexgpt-32k/latest`  | высокое, длинный контекст | ~1.20 ₽                        |

---

## 🤖 Альтернативные LLM-провайдеры

Провайдер переключается в `.env` переменной `LLM_PROVIDER`:

### Groq (бесплатно, быстро)

```env
LLM_PROVIDER=groq
GROQ_API_KEY=gsk_...
GROQ_MODEL=llama-3.3-70b-versatile
TRANSLATE_PROVIDER=groq
```

Получить ключ: https://console.groq.com

### Google Gemini (бесплатно)

```env
LLM_PROVIDER=gemini
GEMINI_API_KEY=AIza...
GEMINI_MODEL=gemini-2.0-flash
TRANSLATE_PROVIDER=gemini
```

Получить ключ: https://ai.google.dev

### Anthropic Claude (платный, лучшее качество)

```env
LLM_PROVIDER=claude
CLAUDE_API_KEY=sk-ant-...
CLAUDE_MODEL=claude-sonnet-4-20250514
TRANSLATE_PROVIDER=claude
```

---

## 🏗️ Архитектура

```
┌──────────────────────────────────────────────────────────┐
│                    Docker Compose                         │
│                                                          │
│  ┌─────────────┐    ┌──────────────────────────────┐    │
│  │  Frontend   │    │         Backend (FastAPI)     │    │
│  │  React/Vite │───>│                              │    │
│  │  :3000      │    │  /api/analyze  → SSE stream  │    │
│  └─────────────┘    │                              │    │
│                     │  ┌──────────┐  ┌──────────┐ │    │
│                     │  │ PubMed   │  │ OpenFDA  │ │    │
│                     │  │ extractor│  │ extractor│ │    │
│                     │  └────┬─────┘  └────┬─────┘ │    │
│                     │       └──────┬───────┘       │    │
│                     │       ┌──────▼───────┐        │    │
│                     │       │DesignRecom-  │        │    │
│                     │       │mender (LLM)  │        │    │
│                     │       └──────┬───────┘        │    │
│                     │              │                │    │
│                     │  ┌───────────▼─────────────┐ │    │
│                     │  │     YandexGPT Provider   │ │    │
│                     │  │  ai.api.cloud.yandex.net │ │    │
│                     │  └──────────────────────────┘ │    │
│                     │              │                │    │
│                     │       ┌──────▼───────┐        │    │
│                     │       │ synopsis.docx│        │    │
│                     │       │ генератор    │        │    │
│                     └───────┴──────────────┴────────┘    │
└──────────────────────────────────────────────────────────┘
```

---

## 🔧 Структура проекта

```
OncoHack/
├── api.py                    # FastAPI backend, SSE endpoints
├── generate_synopsis.py      # Генерация .docx по шаблону
├── synopsis_template.docx    # Официальный шаблон синопсиса
├── main.py                   # CLI-режим (для отладки)
├── .env                      # Конфигурация (не коммитить!)
├── docker-compose.yml        # Оркестрация контейнеров
├── Dockerfile                # Backend контейнер
│
├── extraction/
│   ├── pk_source.py          # Извлечение данных (PubMed, OpenFDA)
│   ├── pk_record.py          # Структура данных PKRecord
│   └── sample_size.py        # Расчёт размера выборки
│
├── models/
│   ├── design_recommender.py # LLM-анализ, выбор дизайна
│   ├── llm_config.py         # Выбор провайдера из .env
│   └── model_providers.py    # Провайдеры: Yandex, Groq, Claude, Gemini, Ollama
│
├── frontend/
│   ├── src/
│   │   ├── App.jsx           # Главный компонент
│   │   ├── components/
│   │   │   ├── ParametersPanel.jsx  # Форма параметров
│   │   │   └── ResultPanel.jsx      # Результаты + прогресс
│   └── Dockerfile
│
└── outputs/                  # Сгенерированные документы (volume)
```

---

## 📊 Критерии выбора дизайна

| Дизайн             | CVintra    | T½     | N участников |
| ------------------------ | ---------- | ------- | ---------------------- |
| 2×2 Cross-over          | < 30%      | < 24 ч | 24–28                 |
| 3-way Replicate          | 30–50%    | < 24 ч | 36–42                 |
| 4-way Replicate (RSABE)  | > 50%      | < 24 ч | 48–60                 |
| Параллельный | любой | > 24 ч | 120+                   |

Нормативная база: **Решение ЕЭК № 85 (2016)**, **FDA BE Guidance (2022)**, **EMA Guideline on BE**.

---

## 🔗 Полезные ссылки

- **Yandex Cloud AI Studio:** https://yandex.cloud/ru/services/foundation-models
- **Yandex Cloud Console:** https://console.yandex.cloud
- **PubMed:** https://pubmed.ncbi.nlm.nih.gov
- **OpenFDA:** https://open.fda.gov
- **API документация (локально):** http://localhost:8000/docs

---

## 📄 Лицензия

MIT License
