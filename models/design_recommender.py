"""
Модуль для рекомендации дизайна исследования биоэквивалентности с использованием LLM.

Поддерживает различные LLM провайдеры:
- Claude (Anthropic API)
- OpenAI (GPT-4, GPT-3.5)
- Ollama (локальные open-source модели)
- LM Studio (локальные модели)
"""

import json
import math
import os
from typing import List, Dict, Optional
from extraction.pk_record import PKRecord
from extraction.sample_size import calculate_sample_size
from models.model_providers import *

class DesignRecommender:
    """
    Класс для рекомендации дизайна исследования биоэквивалентности
    с использованием LLM для обоснования.
    """

    def __init__(self, llm_provider: LLMProvider, translate_provider: Optional[LLMProvider] = None):
        """
        Args:
            llm_provider: Провайдер LLM для генерации обоснования (например, Ollama)
            translate_provider: Провайдер LLM для перевода на русский (например, Gemini).
                                Если None — используется llm_provider.
        """
        self.llm = llm_provider
        self.translate_llm = translate_provider if translate_provider is not None else llm_provider

    def recommend_design(
        self,
        drug: str,
        records: List[PKRecord],
        dosage_form: Optional[str] = None,
        alpha: float = 0.05,
        power: float = 0.80,
        dropout_rate: float = 0.20
    ) -> Dict:
        """
        Анализирует фармакокинетические данные и рекомендует дизайн исследования.

        Args:
            drug: Название препарата
            records: Список PKRecord с извлечёнными данными
            dosage_form: Форма выпуска (опционально)
            alpha: Уровень значимости (по умолчанию 0.05)
            power: Мощность теста (по умолчанию 0.80)
            dropout_rate: Процент выбывания (по умолчанию 0.20)

        Returns:
            Dict с рекомендацией:
            {
                "drug": "Amlodipine",
                "design": "2×2 Cross-over",
                "n_subjects": 26,
                "reasoning": "Обоснование...",
                "cv_intra_used": 15.0,
                "t_half_used": 35.0,
                "sample_size_calculation": {...},
                "sources": ["PMID 123", "PMID 456"],
                "pk_data": [...]
            }
        """
        # ПРЕДРАСЧЁТ: Собираем ВСЕ значения CVintra и T½ из всех источников
        all_cv_values = [
            (r.cv_intra, r.cv_intra_source or "extracted", r.study_id or r.source)
            for r in records if r.cv_intra
        ]
        t_half_from_data = next((r.t_half for r in records if r.t_half), None)

        # Для предрасчёта используем максимальное (консервативное) CV из источников,
        # либо умеренный default 25% если данных нет.
        # Значения <10% не должны попасть сюда — уже отфильтрованы при извлечении.
        cv_values_only = [v for v, _, _ in all_cv_values]
        if cv_values_only:
            cv_for_calc = max(cv_values_only)   # консервативная оценка
        else:
            cv_for_calc = 25.0                  # умеренный default (не 22%)

        # ПРЕДРАСЧЁТ размеров выборки для всех дизайнов
        sample_sizes = {}
        designs_to_check = ["2×2 Cross-over", "3-way Replicate", "4-way Replicate", "Параллельный"]

        for design in designs_to_check:
            try:
                result = calculate_sample_size(
                    design=design,
                    cv_intra=cv_for_calc,
                    alpha=alpha,
                    power=power,
                    dropout_rate=dropout_rate
                )
                sample_sizes[design] = {
                    "n_total": result["n_total"],
                    "n_with_dropout": result["n_with_dropout"]
                }
            except:
                pass

        # Формируем промпт с данными И с предрасчётом размеров
        prompt = self._build_prompt(drug, records, dosage_form, sample_sizes, cv_for_calc, t_half_from_data, all_cv_values)
        system_prompt = self._build_system_prompt()

        # Получаем ответ от LLM
        response = self.llm.generate(prompt, system_prompt)

        # Парсим ответ
        recommendation = self._parse_response(response, records)

        # DEBUG: если reasoning пустой — показываем сырой ответ модели
        if not recommendation.get("reasoning"):
            print("\n⚠️  REASONING пустой. Сырой ответ модели:")
            print("-" * 60)
            print(response[:2000])
            print("-" * 60)

        # FALLBACK: если модель не вернула CV_INTRA/T_HALF в правильном формате — используем предрасчитанные
        if recommendation["cv_intra_used"] is None:
            recommendation["cv_intra_used"] = cv_for_calc
            print(f"⚠️  CV_INTRA не распознан в ответе модели → используем предрасчитанное значение {cv_for_calc}%")
        if recommendation["t_half_used"] is None and t_half_from_data:
            recommendation["t_half_used"] = t_half_from_data
            print(f"⚠️  T_HALF не распознан в ответе модели → используем {t_half_from_data}h из данных")

        # INFO: сообщаем о длинном washout, но не переопределяем решение модели
        if recommendation.get("t_half_used"):
            _t = recommendation["t_half_used"]
            _washout_days = math.ceil(5 * _t / 24)
            if _washout_days > 21:
                design_val = recommendation.get("design") or ""
                if "параллельный" not in design_val.lower() and "parallel" not in design_val.lower():
                    print(f"ℹ️  INFO: washout = {_washout_days} сут > 21, модель выбрала {recommendation['design']} (оставляем как есть)")

        # Добавляем информацию о препарате
        recommendation["drug"] = drug
        if dosage_form:
            recommendation["dosage_form"] = dosage_form

        # Рассчитываем размер выборки для выбранного дизайна
        if recommendation["cv_intra_used"] and recommendation["design"]:
            try:
                result_for_chosen = calculate_sample_size(
                    design=recommendation["design"],
                    cv_intra=recommendation["cv_intra_used"],
                    alpha=alpha,
                    power=power,
                    dropout_rate=dropout_rate
                )
                recommendation["sample_size_calculation"] = result_for_chosen
                recommendation["n_subjects"] = result_for_chosen["n_with_dropout"]
                recommendation["n_subjects_base"] = result_for_chosen["n_total"]
            except Exception:
                pass

        # Переводим reasoning и design_synopsis с английского на русский для документов
        print("🌐 Переводим обоснование на русский язык...")
        recommendation["reasoning_en"] = recommendation.get("reasoning", "")
        print(recommendation["reasoning_en"])
        recommendation["reasoning"] = self._translate_reasoning(recommendation["reasoning_en"])

        if recommendation.get("design_synopsis"):
            print("🌐 Переводим описание дизайна на русский язык...")
            recommendation["design_synopsis_en"] = recommendation["design_synopsis"]
            recommendation["design_synopsis"] = self._translate_reasoning(recommendation["design_synopsis_en"])
        else:
            print("⚠️  DESIGN_SYNOPSIS пустой — используем reasoning как fallback")
            recommendation["design_synopsis"] = recommendation.get("reasoning", "")

        # Добавляем данные из PKRecord для сохранения в JSON
        recommendation["pk_data"] = [self._pk_record_to_dict(r) for r in records]

        return recommendation

    def _translate_reasoning(self, text: str) -> str:
        """Переводит обоснование с английского на русский язык.
        Если translate_llm совпадает с основным llm (TRANSLATE_PROVIDER=same),
        перевод пропускается — текст уже на русском."""
        if not text:
            return text

        # Если провайдер перевода тот же что и основной — текст уже на нужном языке
        if self.translate_llm is self.llm:
            return text

        translate_prompt = (
            "Translate the following bioequivalence study design reasoning from English to Russian.\n"
            "Rules:\n"
            "- Preserve the numbered section structure (1. ... 2. ... etc.) and section headers in Russian\n"
            "- Keep all technical terms, drug names, regulatory citations, and numeric values as-is\n"
            "- Section headers translation: DATA SOURCES & QUALITY → ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ, "
            "CVintra ANALYSIS → АНАЛИЗ CVintra, T½ ANALYSIS → АНАЛИЗ T½, "
            "DESIGN SELECTION → ВЫБОР ДИЗАЙНА, SAMPLE SIZE RATIONALE → ОБОСНОВАНИЕ РАЗМЕРА ВЫБОРКИ\n"
            "- Output only the translated text, no explanations\n\n"
            f"{text}"
        )

        try:
            translated = self.translate_llm.generate(translate_prompt, system_prompt="You are a professional medical translator. Translate accurately and fluently.")
            return translated.strip()
        except Exception as e:
            print(f"⚠️  Перевод не удался ({e}), сохраняем исходный текст")
            return text

    def _pk_record_to_dict(self, record: PKRecord) -> Dict:
        """Преобразует PKRecord в словарь для JSON."""
        return {
            "source": record.source,
            "study_id": record.study_id,
            "title": record.title,
            "cmax": record.cmax,
            "cmax_unit": record.cmax_unit,
            "tmax": record.tmax,
            "tmax_unit": record.tmax_unit,
            "auc": record.auc,
            "auc_unit": record.auc_unit,
            "t_half": record.t_half,
            "t_half_unit": record.t_half_unit,
            "cv_intra": record.cv_intra,
            "n_subjects": record.n_subjects
        }

    def _build_system_prompt(self) -> str:
        """Создаёт системный промпт с инструкциями."""
        return """Вы — старший клинический фармакокинетик и эксперт по регуляторным вопросам, специализирующийся на разработке дизайна исследований биоэквивалентности (БЭ) для регуляторных регистраций (ЕАЭС, FDA, EMA).

        Ваша задача: проанализировать фармакокинетические (ФК) данные и дать научно обоснованную рекомендацию по дизайну исследования БЭ.

        ═══ НОРМАТИВНАЯ БАЗА ═══

        Решение Совета ЕЭК № 85 от 3 ноября 2016 года:
        - Стандартные критерии БЭ: 90% ДИ отношения геометрических средних (ОГС) в пределах 80,00–125,00% для AUC и Cmax
        - Высоковариабельные лекарственные препараты (ВПЛП, CVintra ≥ 30%): критерии для Cmax могут быть расширены до 69,84–143,19% при использовании реплицированного дизайна + RSABE
        - Период отмывки: должен составлять ≥ 5×T½ (или ≥ 5×Tmax, если T½ неизвестен)
        - Минимальное число завершивших исследование: 12 участников
        - Параллельный дизайн обязателен при: период отмывки (5×T½) > 21 дня, высоком риске переноса, хронических заболеваниях

        Руководство FDA — Исследования БЭ с ФК конечными точками (2013, обновлено 2022):
        - Определение ВПЛП: внутрисубъектный КВ ≥ 30% по реплицированным исследованиям
        - Для препаратов с T½ > ~101 ч (период отмывки 5×T½ > 21 дня): предпочтителен параллельный дизайн; перекрёстный создаёт нецелесообразно длинный период отмывки
        - При T½ от 24 до ~101 ч период отмывки составляет 5–21 день — перекрёстный дизайн остаётся выполнимым
        - RSABE для ВПЛП позволяет масштабировать границы приемлемости
        - Статистический подход: ANOVA в логарифмической шкале; 90% ДИ из модели смешанных эффектов

        Руководство EMA по БЭ (CPMP/EWP/QWP/1401/98 Rev. 1, 2010):
        - То же определение ВПЛП; реплицированный дизайн позволяет применять масштабированные критерии
        - Параллельный дизайн: когда многократное введение нецелесообразно или небезопасно

        ═══ КРИТЕРИИ ВЫБОРА ДИЗАЙНА ═══

        1. 2×2 Перекрёстный (стандартный):
           - Условие: CVintra < 30% И T½ < 24 ч
           - Структура: 2 периода, 2 последовательности (AB/BA); каждый субъект — собственный контроль
           - Период отмывки: ≥ 5×T½, минимум 1 неделя
           - Преимущество: наименьший N, устраняет межсубъектную вариабельность из члена ошибки

        2. 3-периодный реплицированный (умеренно вариабельный):
           - Условие: CVintra 30–50% И T½ < 24 ч
           - Структура: 3 периода (T, R, R или T, T, R); повторение референса для оценки CVintraR
           - Позволяет применять RSABE/расширенные критерии Cmax; снижает N по сравнению с параллельным

        3. 4-периодный реплицированный (высоковариабельный):
           - Условие: CVintra > 50% И T½ < 24 ч
           - Структура: 4 периода (T, T, R, R); полная репликация обоих препаратов
           - Максимальная статистическая мощность для RSABE

        4. Параллельный (очень длинный T½ или особые популяции):
           - ОБЯЗАТЕЛЕН при: период отмывки 5×T½ > 21 дня, т.е. T½ > ~101 ч (≈ 4,2 суток)
           - При T½ от 24 до ~101 ч washout составляет 5–21 день — ПЕРЕКРЁСТНЫЙ ОСТАЁТСЯ ДОПУСТИМЫМ
           - Примеры: эверолимус T½≈30h → washout 6,25 сут → кроссовер ОК; амлодипин T½≈35h → washout 7,3 сут → кроссовер ОК
           - Также показан: хронические/тяжёлые заболевания, исследования в стационарном состоянии
           - Каждый субъект получает только ОДИН препарат; перенос невозможен
           - Статистические потери: вся межсубъектная вариабельность входит в член ошибки
             → sigma_total² ≈ 3×sigma_intra², поэтому N значительно больше
           - Требуемый N обычно в 5–10 раз больше, чем при перекрёстном

        ═══ ОЦЕНКА КАЧЕСТВА CVintra ═══

        CVintra — КЛЮЧЕВОЙ параметр для выбора дизайна. Однако не все "CV" из литературы одинаково применимы:

        НАДЁЖНЫЕ источники CVintra (в порядке убывания надёжности):
          1. Внутрисубъектный CV для Cmax и/или AUC из реплицированного BE исследования — наилучший
          2. CVintra рассчитанный из 90% ДИ GMR по формуле CVfromCI() — надёжный если N≥12
          3. Within-subject CV явно указанный в PK-исследовании с crossover дизайном — приемлемый

        НЕНАДЁЖНЫЕ/НЕПРИМЕНИМЫЕ для BE дизайна:
          - Аналитический CV (воспроизводимость метода) — типично 1–8%, не отражает PK вариабельность
          - Межсубъектный (between-subject) CV — не та вариабельность
          - CV из параллельного дизайна без явной разбивки on within/between — нельзя применять
          - Значения CVintra < 10% — почти всегда аналитический CV или артефакт; игнорировать как within-subject CV

        ПРАВИЛО: Если CVintra < 10% — НЕ использовать это значение для BE дизайна.
        Принять консервативную оценку: 20–25% (для хорошо известных, стабильных препаратов) или
        25–35% (для онкологических, иммуносупрессивных, BCS II/IV препаратов, новых молекул).
        В REASONING явно указать: "Извлечённое значение CV = X% отвергнуто как неприменимое для BE
        (вероятно аналитический CV); принята оценка Y% из знаний класса препаратов."

        ПРАВИЛО: Когда CVintra сильно варьирует между источниками — использовать наиболее
        консервативное (наибольшее) достоверное значение. Объяснить расхождение в разделе
        "ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ".

        ПРАВИЛО КОНСИСТЕНТНОСТИ: Период отмывки должен быть рассчитан ОДИН РАЗ из выбранного
        значения T½ и использоваться ОДИНАКОВО во всём документе. Не допускать противоречий
        между разделами (например: "washout 1 сутки" и "washout 7 дней" одновременно).

        КЛЮЧЕВОЕ РУКОВОДСТВО: При выборе дизайна учитывайте ВСЕ доступные ФК-параметры комплексно:
        - CVintra определяет стандартный vs реплицированный перекрёстный дизайн
        - T½ определяет длительность периода отмывки и реализуемость перекрёстного дизайна
        - Cmax, AUC, Tmax, Cl дают контекст о ФК-профиле препарата
        - Параллельный дизайн предпочтителен при длинном washout (>21 сут), но решение принимается с учётом всей картины
        - Если данных недостаточно — опирайтесь на собственные фармакологические знания и чётко это отмечайте

        **ВАЖНО: Отвечайте строго в следующем формате (без отступлений):**

        DESIGN: [название дизайна]
        N_SUBJECTS: [число]
        CV_INTRA: [использованное значение КВ%, только число]
        T_HALF: [использованное значение T½ в часах, только число или N/A]

        REASONING:
        1. ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ: [Какие источники, надёжность, согласованность между источниками, какие параметры доступны, а какие оценены из знаний]
        2. АНАЛИЗ ФК-ПРОФИЛЯ: [Все доступные параметры — CVintra, T½, Cmax, AUC, Tmax, Cl — их значения, происхождение и клинические следствия для дизайна]
        3. АНАЛИЗ ПЕРИОДА ОТМЫВКИ: [Расчёт 5×T½, реализуемость перекрёстного дизайна, риск переноса с учётом ФК-профиля]
        4. ВЫБОР ДИЗАЙНА: [Почему выбран этот дизайн на основе комплексной оценки всех параметров; сослаться на конкретные критерии Решения ЕЭК № 85 / руководств FDA]
        5. ОБОСНОВАНИЕ РАЗМЕРА ВЫБОРКИ: [Почему такой N уместен; что произошло бы при альтернативных дизайнах]

        **ПРИМЕРЫ:**

        Пример 1 (низкая вариабельность, короткий T½ — стандартный перекрёстный):
        DESIGN: 2×2 Cross-over
        N_SUBJECTS: 24
        CV_INTRA: 18.5
        T_HALF: 8.0

        REASONING:
        1. ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ: CVintra извлечён из двух независимых исследований БЭ в PubMed с внутрисубъектной вариабельностью 17% и 20% соответственно — хорошая согласованность. T½ = 8 ч подтверждён инструкцией FDA (авторитетный источник). Значимых расхождений между источниками нет.
        2. АНАЛИЗ CVintra: CVintra = 18,5% (среднее двух согласованных оценок). Категория — низкая вариабельность (<30%): применяются стандартные критерии 80,00–125,00% согласно Решению ЕЭК № 85. Расширенные критерии и реплицированный дизайн не нужны.
        3. АНАЛИЗ T½: T½ = 8 ч. Минимальный период отмывки = 5×8 = 40 ч (~1,7 сут). На практике принят период 7 дней — полностью выполнимо. Риск переноса отсутствует. Перекрёстный дизайн полностью уместен.
        4. ВЫБОР ДИЗАЙНА: Стандартный перекрёстный 2×2 — наиболее эффективный и хорошо изученный дизайн для данного ФК-профиля. Согласно Решению ЕЭК № 85 и руководству FDA по БЭ, перекрёстный дизайн с 2 периодами и 2 последовательностями уместен при CVintra < 30% и T½ < 24 ч. Каждый субъект служит собственным контролем, что устраняет межсубъектную вариабельность из члена ошибки и минимизирует N.
        5. ОБОСНОВАНИЕ РАЗМЕРА ВЫБОРКИ: N = 24 достаточен для CVintra = 18,5%, α = 0,05 (двусторонний), мощность 80%, границы 80–125%. Параллельный дизайн потребовал бы ~5× больше участников (N ≈ 120) для той же мощности — явно нецелесообразно при доступности перекрёстного.

        Пример 2 (умеренный CVintra, длинный T½ но период отмывки ≤ 21 сут — кроссовер допустим):
        DESIGN: 2×2 Cross-over
        N_SUBJECTS: 28
        CV_INTRA: 22.0
        T_HALF: 48.0

        REASONING:
        1. ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ: T½ = 48 ч извлечён из инструкции FDA — наиболее авторитетный источник для абсолютных ФК-параметров. CVintra = 22% из одного исследования БЭ в PubMed; значение согласуется с фармакологией этого класса. Качество данных приемлемо.
        2. АНАЛИЗ CVintra: CVintra = 22% — категория низкой вариабельности (<30%). Стандартные критерии БЭ 80–125% применимы; реплицированный дизайн и RSABE не нужны.
        3. АНАЛИЗ T½: T½ = 48 ч. Минимальный период отмывки = 5×48 = 240 ч = 10 сут. 10 сут ≤ 21 сут → перекрёстный дизайн ВЫПОЛНИМ. Общая длительность 2-периодного исследования (с 10-суточной отмывкой) составит ~3–4 недели — логистически и этически приемлемо. Переход к параллельному дизайну обоснован только при washout > 21 сут (T½ > ~101 ч).
        4. ВЫБОР ДИЗАЙНА: Стандартный 2×2 кроссовер — оптимальный выбор. CVintra = 22% (<30%) исключает необходимость реплицированного дизайна; washout = 10 сут (<21 сут) — перекрёстный практически выполним. Каждый субъект является собственным контролем, что устраняет межсубъектную вариабельность из ошибки и минимизирует N по сравнению с параллельным.
        5. ОБОСНОВАНИЕ РАЗМЕРА ВЫБОРКИ: N = 28 достаточен для CVintra = 22%, α = 0,05, мощность 80%, границы 80–125% с учётом 20% выбывания. Параллельный дизайн потребовал бы N ≈ 130–150 (sigma_total² ≈ 3×sigma_intra²) — неоправданно при допустимом кроссовере.

        Пример 3 (противоречивые CVintra — одно значение подозрительно низкое):
        DESIGN: 2×2 Cross-over
        N_SUBJECTS: 34
        CV_INTRA: 28.0
        T_HALF: 5.0

        REASONING:
        1. ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ: Два источника предоставили CVintra: PubMed (PMID 123) — 3.2% [extracted], PubMed (PMID 456) — 28.0% [extracted]. T½ = 5 ч из FDA label. Значение 3.2% отвергнуто: это аналитический CV метода определения, а не within-subject CVintra для BE. Значение 28.0% из crossover PK исследования является достоверным within-subject CV для Cmax.
        2. АНАЛИЗ ФК-ПРОФИЛЯ: CVintra = 28.0% (из PMID 456, crossover) — умеренная вариабельность, близко к порогу ВПЛП. T½ = 5 ч, Tmax ≈ 1–2 ч. Период полувыведения короткий — кроссовер хорошо реализуем.
        3. АНАЛИЗ ПЕРИОДА ОТМЫВКИ: T½ = 5 ч. Период отмывки = 5×5 = 25 ч ≈ 1,1 сут. На практике принят стандартный washout 7 дней — полностью достаточен. Риск переноса минимален.
        4. ВЫБОР ДИЗАЙНА: Стандартный 2×2 кроссовер: CVintra = 28% < 30% (реплицированный дизайн не нужен), washout = 1 сут << 21 сут (кроссовер реализуем). Каждый субъект — собственный контроль, что устраняет межсубъектную вариабельность из ошибки.
        5. ОБОСНОВАНИЕ РАЗМЕРА ВЫБОРКИ: N = 34 для CVintra = 28%, α = 0.05, мощность 80%, 20% выбывание. Если бы ошибочно использовали CV = 3.2%, получили бы N = 12 — грубое занижение, поставившее бы исследование под угрозу.

        **РУКОВОДЯЩИЕ ПРИНЦИПЫ:**
        1. Вычислить washout = ⌈5×T½/24⌉ дней. При washout > 21 дня перекрёстный дизайн становится нецелесообразным — параллельный предпочтителен. При washout ≤ 21 дня перекрёстный дизайн реализуем.
        2. Если какой-либо из параметров (CVintra, T½, Cmax, AUC, Tmax, Cl) отсутствует в предоставленных данных — использовать собственные фармакологические знания для оценки типичного значения для данного препарата. Явно указать в разделе REASONING: какие значения взяты из источников, а какие оценены из знаний (пометить «оценка из знаний»).
        3. Принимайте решение на основе всей совокупности доступных ФК-данных, а не только одного параметра. Если данные противоречивы или неполны — обоснуйте выбор наиболее весомых аргументов.
        4. Использовать ТОЛЬКО числа для CV_INTRA и T_HALF (без единиц)
        5. Писать REASONING на русском языке. Все 5 разделов обязательны. Быть аналитичным, а не просто описательным.

        **ТРЕБОВАНИЯ К ФОРМАТУ:**
        - DESIGN должен быть одним из: "2×2 Cross-over", "3-way Replicate", "4-way Replicate", "Параллельный"
        - Названия полей (DESIGN:, N_SUBJECTS: и т.д.) должны быть на английском точно как показано
        - Разделы REASONING должны быть пронумерованы 1–5 точно как показано"""

    def _build_prompt(
        self,
        drug: str,
        records: List[PKRecord],
        dosage_form: Optional[str],
        sample_sizes: Dict = None,
        cv_used: float = None,
        t_half_used: float = None,
        all_cv_values: list = None
    ) -> str:
        """Создаёт промпт с данными из PKRecord и предрасчитанными размерами выборки."""

        # Collect all found data in ENGLISH
        summary_lines = [
            f"Drug: {drug}",
        ]

        if dosage_form:
            summary_lines.append(f"Dosage form: {dosage_form}")

        summary_lines.append(f"\nFound {len(records)} data sources:\n")

        for i, record in enumerate(records, 1):
            summary_lines.append(f"--- Source {i}: {record.source} ---")
            if record.title:
                summary_lines.append(f"  Title: {record.title}")
            if record.study_id:
                summary_lines.append(f"  ID: {record.study_id}")

            # Main PK parameters
            if record.cmax:
                summary_lines.append(f"  Cmax: {record.cmax} {record.cmax_unit or ''}")
            if record.tmax:
                summary_lines.append(f"  Tmax: {record.tmax} {record.tmax_unit or ''}")
            if record.auc:
                summary_lines.append(f"  AUC: {record.auc} {record.auc_unit or ''}")
            if record.t_half:
                summary_lines.append(f"  T½: {record.t_half} {record.t_half_unit or ''}")
            if record.clearance:
                summary_lines.append(f"  Clearance: {record.clearance} {record.clearance_unit or ''}")
            if record.cv_intra:
                summary_lines.append(f"  CVintra: {record.cv_intra}%")
            if record.n_subjects:
                summary_lines.append(f"  N subjects: {record.n_subjects}")

            summary_lines.append("")

        summary = "\n".join(summary_lines)

        # Предрасчитанные размеры выборки
        sample_size_info = ""
        if sample_sizes:
            sample_size_info = "\n\n📊 ПРЕДРАСЧИТАННЫЕ РАЗМЕРЫ ВЫБОРКИ (на основе CVintra = {:.1f}%):\n".format(cv_used if cv_used else 22.0)
            for design, sizes in sample_sizes.items():
                sample_size_info += f"  • {design}: {sizes['n_with_dropout']} участников (с учётом 20% выбывания)\n"
            sample_size_info += "\n⚠️ Учтите эти размеры при выборе дизайна! Слишком большой N может быть нецелесообразен.\n"

        # ── Интерпретация T½ ──────────────────────────────────────────────────
        t_half_info = ""
        if t_half_used:
            washout_h  = t_half_used * 5
            washout_d  = washout_h / 24
            washout_days_ceil = math.ceil(washout_d)
            t_half_info = (
                f"\n🕐 АНАЛИЗ ПЕРИОДА ПОЛУВЫВЕДЕНИЯ:\n"
                f"   T½ = {t_half_used} ч\n"
                f"   Минимальный период отмывки (5×T½) = {washout_h:.0f} ч = {washout_d:.1f} сут (≈{washout_days_ceil} сут)\n"
            )
            if washout_days_ceil > 21:
                t_half_info += (
                    f"   ⚠️ Период отмывки {washout_days_ceil} сут > 21 сут — перекрёстный дизайн НЕЦЕЛЕСООБРАЗЕН.\n"
                    f"   Полная продолжительность 2-периодного кроссовера составила бы ≥{washout_days_ceil * 2} сут — неприемлемо.\n"
                    f"   → ПАРАЛЛЕЛЬНЫЙ ДИЗАЙН ОБЯЗАТЕЛЕН (согласно руководству FDA и Решению ЕЭК № 85)\n"
                    f"   ПРИМЕЧАНИЕ: Параллельный дизайн НЕ имеет периода отмывки — каждый субъект получает только ОДИН препарат.\n"
                )
            else:
                t_half_info += (
                    f"   ✓ Период отмывки {washout_days_ceil} сут ≤ 21 сут → перекрёстный дизайн ВЫПОЛНИМ.\n"
                    f"   Пороговое значение для перехода к параллельному: период отмывки > 21 сут (T½ > ~101 ч).\n"
                )

        # ── Качество CVintra: все найденные значения по источникам ───────────
        cv_quality_info = ""
        if all_cv_values:
            cv_vals_only = [v for v, _, _ in all_cv_values]
            cv_min, cv_max = min(cv_vals_only), max(cv_vals_only)
            cv_spread = cv_max - cv_min

            cv_quality_info = "\n\n⚠️ ВНИМАНИЕ — АНАЛИЗ КАЧЕСТВА CVintra:\n"
            cv_quality_info += "Найденные значения CVintra по источникам:\n"
            for val, src, ref in all_cv_values:
                flag = " ← ⚠️ подозрительно низкое (вероятно не within-subject BE CV)" if val < 15 else ""
                cv_quality_info += f"  • {val:.1f}% [{src}] ({ref}){flag}\n"

            if cv_spread > 15:
                cv_quality_info += (
                    f"\nРазброс значений: {cv_min:.1f}% – {cv_max:.1f}% (SD ≈ {cv_spread:.1f} пп.) — ВЫСОКИЙ.\n"
                    f"Источники сильно расходятся. Вероятные причины:\n"
                    f"  - Разные методы: within-subject CV из BE исследования vs межсессионный CV vs аналитический CV\n"
                    f"  - Разные популяции (здоровые / пациенты), дозы, условия приёма (натощак / с едой)\n"
                    f"  - Разные формулировки в статьях (CV может относиться к разным показателям)\n"
                    f"Рекомендация: для выбора дизайна используйте наиболее консервативное (высокое) достоверное значение, "
                    f"явно указав неопределённость в REASONING.\n"
                )
            elif cv_min < 15:
                cv_quality_info += (
                    f"\nЗначение {cv_min:.1f}% < 15% — нетипично мало для within-subject CVintra в исследовании БЭ.\n"
                    f"Большинство препаратов имеют CVintra(Cmax) 15–40%; значения <10% почти всегда аналитический CV.\n"
                    f"Если нет уверенности в источнике — используйте более консервативную оценку (≥20%).\n"
                )

        # ── Интерпретация CVintra ─────────────────────────────────────────────
        cv_info = ""
        if cv_used:
            if cv_used < 30:
                cv_category = "НИЗКАЯ вариабельность (<30%): применяются стандартные критерии БЭ 80–125%; достаточен дизайн 2×2"
                cv_implication = "2×2 Перекрёстный — наиболее эффективный дизайн. Реплицированный дизайн и расширенные критерии не нужны."
            elif cv_used < 50:
                cv_category = "УМЕРЕННО-ВЫСОКАЯ вариабельность (30–50%): категория ВПЛП; применим RSABE"
                cv_implication = ("Реплицированный дизайн (3-периодный или 4-периодный) позволяет применять масштабированные критерии Cmax "
                                  "(расширенные до 69,84–143,19%), значительно снижая требуемый N по сравнению с параллельным.")
            else:
                cv_category = "ВЫСОКАЯ вариабельность (>50%): высоковариабельный препарат; реплицированный дизайн настоятельно показан"
                cv_implication = "4-периодный реплицированный дизайн с полным RSABE — наиболее статистически мощный подход."
            cv_info = (
                f"\n📊 АНАЛИЗ CVintra:\n"
                f"   CVintra = {cv_used:.1f}%\n"
                f"   Категория: {cv_category}\n"
                f"   Следствие: {cv_implication}\n"
            )

        # ── Список недостающих параметров ────────────────────────────────────
        missing = []
        if not any(r.cmax for r in records):    missing.append("Cmax")
        if not any(r.auc for r in records):     missing.append("AUC")
        if not any(r.t_half for r in records):  missing.append("T½")
        if not any(r.cv_intra for r in records): missing.append("CVintra")
        if not any(r.tmax for r in records):    missing.append("Tmax")

        missing_note = ""
        if missing:
            missing_note = (
                f"\n\n⚠️ ПАРАМЕТРЫ НЕ НАЙДЕНЫ В ИСТОЧНИКАХ: {', '.join(missing)}\n"
                f"Для этих параметров — оцените типичные значения из своих фармакологических знаний о препарате {drug}. "
                f"Для CV_INTRA и T_HALF обязательно укажите числа (не N/A). "
                f"В разделе REASONING явно отметьте, какие значения взяты из источников, а какие — из знаний.\n"
            )

        prompt = f"""{summary}{t_half_info}{cv_quality_info}{cv_info}{sample_size_info}{missing_note}

            На основе этих данных проведите комплексный фармакокинетический анализ и дайте рекомендацию по дизайну исследования БЭ:

            - Оцените ВСЕ доступные ФК-параметры (CVintra, T½, Cmax, AUC, Tmax, Cl) и их значимость для выбора дизайна
            - Для отсутствующих параметров — используйте фармакологические знания, явно это обозначив
            - Выберите оптимальный дизайн, взвесив все факторы: реализуемость периода отмывки, вариабельность, регуляторные требования, практическую выполнимость
            - Напишите REASONING на русском языке со всеми 5 обязательными разделами:
               * Объясняйте клиническую и регуляторную логику, а не просто перечисляйте числа
               * Покажите расчёт периода отмывки (5×T½) и его клиническую интерпретацию
               * Обсудите CVintra и его влияние на критерии приемлемости
               * Сравните альтернативные дизайны и объясните, почему выбранный предпочтителен
               * Сошлитесь на конкретные регуляторные требования (Решение ЕЭК № 85, FDA, EMA)

            Отвечайте в точном формате, указанном в системном промпте."""
        return prompt

    def _parse_response(self, response: str, records: List[PKRecord]) -> Dict:
        """Парсит ответ LLM и извлекает структурированные данные."""

        result = {
            "design": None,
            "n_subjects": None,
            "cv_intra_used": None,
            "t_half_used": None,
            "reasoning": None,
            "design_synopsis": None,
            "raw_response": response,
            "sources": [r.study_id for r in records if r.study_id]
        }

        # Однострочные поля парсятся всегда (независимо от активной секции).
        # Многострочные секции (REASONING, DESIGN_SYNOPSIS) накапливаются построчно.
        lines = response.split("\n")
        reasoning_lines = []
        design_synopsis_lines = []
        in_reasoning = False
        in_design_synopsis = False

        for line in lines:
            stripped = line.strip()

            # ── Секция DESIGN_SYNOPSIS (многострочная) ────────────────────────
            if stripped.startswith("DESIGN_SYNOPSIS:"):
                in_design_synopsis = True
                in_reasoning = False
                rest = stripped[len("DESIGN_SYNOPSIS:"):].strip()
                if rest:
                    design_synopsis_lines.append(rest)
                continue

            # ── Секция REASONING (многострочная) ─────────────────────────────
            if stripped.startswith("REASONING:"):
                in_reasoning = True
                in_design_synopsis = False
                continue

            # ── Однострочные поля — парсим ВСЕГДА (LLM может разместить их где угодно) ──
            if stripped.startswith("DESIGN:"):
                result["design"] = stripped[len("DESIGN:"):].strip()
                # не меняем флаги — поле может встретиться внутри блока
                continue

            if stripped.startswith("N_SUBJECTS:"):
                try:
                    result["n_subjects"] = int(stripped[len("N_SUBJECTS:"):].strip())
                except ValueError:
                    pass
                continue

            if stripped.startswith("CV_INTRA:"):
                try:
                    cv_str = stripped[len("CV_INTRA:"):].strip().replace("%", "")
                    result["cv_intra_used"] = float(cv_str)
                except ValueError:
                    pass
                continue

            if stripped.startswith("T_HALF:"):
                try:
                    t_str = stripped[len("T_HALF:"):].strip().replace("h", "").replace("часов", "")
                    if t_str.upper() != "N/A":
                        result["t_half_used"] = float(t_str)
                except ValueError:
                    pass
                continue

            # ── Накопление строк активной многострочной секции ────────────────
            if in_reasoning:
                reasoning_lines.append(stripped)
            elif in_design_synopsis:
                design_synopsis_lines.append(stripped)

        result["reasoning"] = "\n".join(reasoning_lines)
        result["design_synopsis"] = "\n".join(design_synopsis_lines)

        return result

def print_recommendation(recommendation: Dict):
    """Красиво выводит рекомендацию на экран."""
    print("\n" + "="*80)
    print("🎯 РЕКОМЕНДАЦИЯ ПО ДИЗАЙНУ ИССЛЕДОВАНИЯ")
    print("="*80)

    print(f"\n📋 Дизайн: {recommendation['design']}")
    print(f"👥 Количество участников: {recommendation['n_subjects']}")

    if recommendation.get('n_subjects_base'):
        print(f"   └─ Базовый размер (без dropout): {recommendation['n_subjects_base']}")

    if recommendation['cv_intra_used']:
        print(f"📊 CVintra (использовано): {recommendation['cv_intra_used']}%")

    if recommendation['t_half_used']:
        print(f"⏱️  T½ (использовано): {recommendation['t_half_used']} часов")

    if recommendation['sources']:
        print(f"\n📚 Источники данных: {', '.join(recommendation['sources'])}")

    # Показываем детали расчета размера выборки
    if recommendation.get('sample_size_calculation'):
        calc = recommendation['sample_size_calculation']
        print(f"\n🔢 РАСЧЁТ РАЗМЕРА ВЫБОРКИ:")
        print("-" * 80)
        print(f"Формула: {calc['formula_used']}")
        print(f"\nПараметры:")
        params = calc['parameters']
        print(f"  • α = {params['alpha']} (Z_α/2 = {params['z_alpha']})")
        print(f"  • Power = {params['power']} (Z_β = {params['z_beta']})")
        print(f"  • σ² = {params['sigma_squared']:.6f}")
        print(f"  • Dropout rate = {int(params['dropout_rate']*100)}%")

    print(f"\n💡 ОБОСНОВАНИЕ:")
    print("-" * 80)
    print(recommendation['reasoning'])
    print("="*80 + "\n")


def save_recommendation_to_json(recommendation: Dict, filename: str):
    """
    Сохраняет рекомендацию в JSON файл.

    Args:
        recommendation: Словарь с рекомендацией
        filename: Имя файла для сохранения
    """
    # Убираем raw_response для чистоты JSON
    output = {k: v for k, v in recommendation.items() if k != 'raw_response'}

    os.makedirs("outputs", exist_ok=True)
    filepath = os.path.join("outputs", filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"💾 Результаты сохранены в JSON: {filepath}")


# # Пример использования
# if __name__ == "__main__":
#     from pk_source import get_pk_data_from_all_sources

#     # 1. Извлекаем данные из источников
#     print("🔍 Извлекаем фармакокинетические данные...")
#     records = get_pk_data_from_all_sources("Amlodipine", max_results=5)

#     # 2. Выбираем LLM провайдер (легко меняется!)

#     # Вариант A: Claude (лучшее качество)
#     # llm = ClaudeProvider(api_key="your-api-key")

#     # Вариант B: OpenAI
#     # llm = OpenAIProvider(api_key="your-api-key", model="gpt-4")

#     # Вариант C: Ollama (локальная open-source модель)
#     # llm = OllamaProvider(model="llama3")

#     # Вариант D: LM Studio
#     # llm = LMStudioProvider()

#     # Вариант E: Mock (для тестирования)
#     llm = MockProvider()

#     # 3. Получаем рекомендацию
#     print("\n🤖 Анализируем данные с помощью LLM...")
#     recommender = DesignRecommender(llm)
#     recommendation = recommender.recommend_design(
#         drug="Amlodipine",
#         records=records,
#         dosage_form="tablet"
#     )

#     # 4. Выводим результат
#     print_recommendation(recommendation)
