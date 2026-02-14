"""
Модуль для рекомендации дизайна исследования биоэквивалентности с использованием LLM.

Поддерживает различные LLM провайдеры:
- Claude (Anthropic API)
- OpenAI (GPT-4, GPT-3.5)
- Ollama (локальные open-source модели)
- LM Studio (локальные модели)
"""

import json
from typing import List, Dict, Optional
from extraction.pk_record import PKRecord
from extraction.sample_size import calculate_sample_size
from models.model_providers import *

class DesignRecommender:
    """
    Класс для рекомендации дизайна исследования биоэквивалентности
    с использованием LLM для обоснования.
    """

    def __init__(self, llm_provider: LLMProvider):
        """
        Args:
            llm_provider: Провайдер LLM (Claude, OpenAI, Ollama и т.д.)
        """
        self.llm = llm_provider

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
        # ПРЕДРАСЧЁТ: Определяем CVintra и T½ из данных
        cv_from_data = None
        t_half_from_data = None

        for r in records:
            if r.cv_intra and not cv_from_data:
                cv_from_data = r.cv_intra
            if r.t_half and not t_half_from_data:
                t_half_from_data = r.t_half

        # Используем типичное значение если не найдено
        cv_for_calc = cv_from_data if cv_from_data else 22.0

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
        prompt = self._build_prompt(drug, records, dosage_form, sample_sizes, cv_for_calc, t_half_from_data)
        system_prompt = self._build_system_prompt()

        # Получаем ответ от LLM
        response = self.llm.generate(prompt, system_prompt)

        # Парсим ответ
        recommendation = self._parse_response(response, records)

        # SAFETY NET: Проверяем T½ > 24h → должен быть Параллельный дизайн
        if recommendation.get("t_half_used") and recommendation["t_half_used"] > 24:
            if "параллельный" not in recommendation.get("design", "").lower() and "parallel" not in recommendation.get("design", "").lower():
                print(f"⚠️  WARNING: T½ = {recommendation['t_half_used']}h > 24h, но модель выбрала {recommendation['design']}")
                print(f"   Автоматически меняем на Параллельный дизайн")
                recommendation["design"] = "Параллельный"
                recommendation["reasoning"] += f"\n\n[Автокоррекция: T½ = {recommendation['t_half_used']}h > 24h требует параллельного дизайна по FDA guidance]"

        # Добавляем информацию о препарате
        recommendation["drug"] = drug
        if dosage_form:
            recommendation["dosage_form"] = dosage_form

        # Рассчитываем размер выборки на основе рекомендации LLM
        if recommendation["cv_intra_used"] and recommendation["design"]:
            # Добавляем детали расчета
            recommendation["sample_size_calculation"] = result
            # Обновляем n_subjects из расчета
            recommendation["n_subjects"] = result["n_with_dropout"]
            recommendation["n_subjects_base"] = result["n_total"]

        # Добавляем данные из PKRecord для сохранения в JSON
        recommendation["pk_data"] = [self._pk_record_to_dict(r) for r in records]

        return recommendation

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
        return """You are an expert in pharmacokinetics and bioequivalence study design.

        Your task: Analyze pharmacokinetic data and recommend a bioequivalence study design.

        Design Selection Criteria:
        1. **2×2 Cross-over**: CVintra ≤ 30%, standard drugs, typical N = 24-28
        2. **3-way Replicate**: CVintra 30-50%, moderately variable, typical N = 36-42
        3. **4-way Replicate**: CVintra > 50%, highly variable, typical N = 48-60
        4. **Parallel**: T½ > 24h (mandatory) OR impractical crossover, typical N = 150+

        **Important:** T½ > 24 hours → MUST choose Parallel design regardless of CVintra!

        **CRITICAL: You MUST respond in this EXACT format (no deviations):**

        DESIGN: [design name]
        N_SUBJECTS: [number]
        CV_INTRA: [CV% value used, number only]
        T_HALF: [T½ hours used, number only or N/A]

        REASONING:
        [2-3 sentences explaining the choice based on the data]

        **EXAMPLES:**

        Example 1 (Low variability drug):
        DESIGN: 2×2 Cross-over
        N_SUBJECTS: 24
        CV_INTRA: 18.5
        T_HALF: 8.0

        REASONING:
        CVintra of 18.5% indicates low variability, suitable for standard 2×2 crossover design. Half-life of 8 hours allows adequate washout period. This design provides sufficient power with minimal sample size.

        Example 2 (Long half-life drug):
        DESIGN: Параллельный
        N_SUBJECTS: 150
        CV_INTRA: 22.0
        T_HALF: 48.0

        REASONING:
        Despite moderate CVintra of 22%, the long half-life (48h > 24h) makes crossover design impractical due to prolonged washout requirements. Parallel design is recommended for drugs with T½ > 24 hours per FDA guidance.

        **CRITICAL RULES (MUST FOLLOW):**
        1. **T½ > 24 hours → ALWAYS use "Параллельный" design, NO EXCEPTIONS!**
        2. If CVintra not in data → use typical 20-25%
        3. If T½ in data → check rule #1 FIRST before choosing design
        4. Use ONLY numbers for CV_INTRA and T_HALF (no units)
        5. Keep REASONING concise (2-3 sentences)

        **FORMAT REQUIREMENTS:**
        - DESIGN must be one of: "2×2 Cross-over", "3-way Replicate", "4-way Replicate", "Параллельный"
        - Respond in English or Russian, but field names must be exact"""

    def _build_prompt(
        self,
        drug: str,
        records: List[PKRecord],
        dosage_form: Optional[str],
        sample_sizes: Dict = None,
        cv_used: float = None,
        t_half_used: float = None
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

        # Add pre-calculated sample sizes information
        sample_size_info = ""
        if sample_sizes:
            sample_size_info = "\n\n📊 PRE-CALCULATED SAMPLE SIZES (based on CVintra = {:.1f}%):\n".format(cv_used if cv_used else 22.0)
            for design, sizes in sample_sizes.items():
                sample_size_info += f"  • {design}: {sizes['n_with_dropout']} subjects (with 20% dropout)\n"
            sample_size_info += "\n⚠️ Consider these sizes when choosing design! Too large N may be impractical.\n"

        t_half_info = ""
        if t_half_used:
            t_half_info = f"\n🕐 Half-life from data: T½ = {t_half_used} hours\n"
            if t_half_used > 24:
                t_half_info += "   ⚠️ T½ > 24h → MUST use Parallel design!\n"

        prompt = f"""{summary}{t_half_info}{sample_size_info}

            Based on this data:
            1. Determine which CVintra to use (from data or typical value ~22%)
            2. Select appropriate bioequivalence study design considering:
            - CVintra level (low/moderate/high variability)
            - T½ (if > 24h → Parallel design mandatory)
            - Practical sample size from table above
            3. Take N_SUBJECTS from the pre-calculated table above for your chosen design
            4. Provide concise reasoning (2-3 sentences) explaining your choice

            Respond in the EXACT format specified in system prompt."""
        return prompt

    def _parse_response(self, response: str, records: List[PKRecord]) -> Dict:
        """Парсит ответ LLM и извлекает структурированные данные."""

        result = {
            "design": None,
            "n_subjects": None,
            "cv_intra_used": None,
            "t_half_used": None,
            "reasoning": None,
            "raw_response": response,
            "sources": [r.study_id for r in records if r.study_id]
        }

        # Извлекаем структурированные поля
        lines = response.split("\n")
        reasoning_lines = []
        in_reasoning = False

        for line in lines:
            line = line.strip()

            if line.startswith("DESIGN:"):
                result["design"] = line.replace("DESIGN:", "").strip()
            elif line.startswith("N_SUBJECTS:"):
                try:
                    result["n_subjects"] = int(line.replace("N_SUBJECTS:", "").strip())
                except ValueError:
                    pass
            elif line.startswith("CV_INTRA:"):
                try:
                    cv_str = line.replace("CV_INTRA:", "").strip().replace("%", "")
                    result["cv_intra_used"] = float(cv_str)
                except ValueError:
                    pass
            elif line.startswith("T_HALF:"):
                try:
                    t_str = line.replace("T_HALF:", "").strip().replace("h", "").replace("часов", "")
                    result["t_half_used"] = float(t_str)
                except ValueError:
                    pass
            elif line.startswith("REASONING:"):
                in_reasoning = True
            elif in_reasoning and line:
                reasoning_lines.append(line)

        result["reasoning"] = "\n".join(reasoning_lines)

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

    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"💾 Результаты сохранены в JSON: {filename}")


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
