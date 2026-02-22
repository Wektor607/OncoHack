"""
Модуль для рекомендации дизайна исследования биоэквивалентности с использованием LLM.

Поддерживает различные LLM провайдеры:
- Claude (Anthropic API)
- OpenAI (GPT-4, GPT-3.5)
- Ollama (локальные open-source модели)
- LM Studio (локальные модели)
"""

import json
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

        # SAFETY NET: Проверяем T½ > 24h → должен быть Параллельный дизайн
        if recommendation.get("t_half_used") and recommendation["t_half_used"] > 24:
            design_val = recommendation.get("design") or ""
            if "параллельный" not in design_val.lower() and "parallel" not in design_val.lower():
                print(f"⚠️  WARNING: T½ = {recommendation['t_half_used']}h > 24h, но модель выбрала {recommendation['design']}")
                print(f"   Автоматически меняем на Параллельный дизайн")
                recommendation["design"] = "Параллельный"
                recommendation["reasoning"] += f"\n\n[Автокоррекция: T½ = {recommendation['t_half_used']}h > 24h требует параллельного дизайна по FDA guidance]"

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

    def _translate_reasoning(self, text_en: str) -> str:
        """Переводит обоснование с английского на русский язык."""
        if not text_en:
            return text_en

        translate_prompt = (
            "Translate the following bioequivalence study design reasoning from English to Russian.\n"
            "Rules:\n"
            "- Preserve the numbered section structure (1. ... 2. ... etc.) and section headers in Russian\n"
            "- Keep all technical terms, drug names, regulatory citations, and numeric values as-is\n"
            "- Section headers translation: DATA SOURCES & QUALITY → ИСТОЧНИКИ И КАЧЕСТВО ДАННЫХ, "
            "CVintra ANALYSIS → АНАЛИЗ CVintra, T½ ANALYSIS → АНАЛИЗ T½, "
            "DESIGN SELECTION → ВЫБОР ДИЗАЙНА, SAMPLE SIZE RATIONALE → ОБОСНОВАНИЕ РАЗМЕРА ВЫБОРКИ\n"
            "- Output only the translated text, no explanations\n\n"
            f"{text_en}"
        )

        try:
            translated = self.translate_llm.generate(translate_prompt, system_prompt="You are a professional medical translator. Translate accurately and fluently.")
            return translated.strip()
        except Exception as e:
            print(f"⚠️  Перевод не удался ({e}), сохраняем английский текст")
            return text_en

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
        return """You are a senior clinical pharmacokineticist and regulatory affairs expert specializing in bioequivalence (BE) study design for regulatory submissions (EAEU, FDA, EMA).

        Your task: Analyze pharmacokinetic (PK) data and provide a scientifically rigorous justification for a BE study design recommendation.

        ═══ REGULATORY FRAMEWORK ═══

        EAEU Decision No. 85 (Eurasian Economic Commission Council, November 3, 2016):
        - Standard BE acceptance criteria: 90% CI of geometric mean ratio (GMR) within 80.00–125.00% for AUC and Cmax
        - Highly Variable Drug Products (HVDPs, CVintra ≥ 30%): Cmax criteria may be widened to 69.84–143.19% using replicated design + Reference-Scaled Average BE (RSABE)
        - Washout period: must be ≥ 5×T½ (or ≥ 5×Tmax if T½ unknown)
        - Minimum completed sample: 12 subjects
        - Parallel design required when: T½ > 24h, carry-over risk is high, chronic disease population

        FDA Guidance for Industry – Bioequivalence Studies with Pharmacokinetic Endpoints (2013, updated 2022):
        - HVDP definition: intrasubject CV ≥ 30% based on replicated studies
        - For drugs with T½ > 24h: parallel-group design preferred; crossover creates impractical washout (e.g., T½ = 30h → washout ≥ 150h = 6.25 days minimum, but more practically 2–3 weeks)
        - RSABE for HVDP allows scaling acceptance limits using within-subject SD of reference
        - Statistical approach: ANOVA on log-transformed data; 90% CI from mixed-effects model for replicated designs

        EMA Guideline on BE (CPMP/EWP/QWP/1401/98 Rev. 1, 2010):
        - Same HVDP definition; replicated design enables reference-scaled criteria
        - Parallel design: when repeated administration is impractical or unsafe

        ═══ DESIGN SELECTION CRITERIA ═══

        1. 2x2 Cross-over (standard):
           - Condition: CVintra < 30% AND T½ < 24h
           - Structure: 2 periods, 2 sequences (AB/BA); each subject is own control
           - Washout: ≥ 5×T½, minimum 1 week
           - Advantage: smallest N, eliminates between-subject variability from error term
           - Limitation: at CVintra ≥ 30%, standard 80–125% criteria require large N

        2. 3-way Replicated (moderately variable):
           - Condition: CVintra 30–50% AND T½ < 24h
           - Structure: 3 periods (T, R, R or T, T, R); reference repeated to estimate CVintraR
           - Enables RSABE/widened Cmax criteria; reduces N vs. parallel for same power
           - Practical: 3 inpatient stays, total duration ~3×(dosing day + washout)

        3. 4-way Replicated (highly variable):
           - Condition: CVintra > 50% AND T½ < 24h
           - Structure: 4 periods (T, T, R, R); full replication of both products
           - Maximum statistical power for RSABE; needed when CVintra is very high
           - Practical burden: 4 inpatient visits, long total study duration

        4. Parallel (long T½ or special populations):
           - MANDATORY when: T½ > 24h (crossover becomes impractical)
           - Also indicated: chronic/serious disease, safety/tolerability concerns, stable-state studies
           - Each subject receives only ONE product (no carry-over possible)
           - Statistical penalty: all between-subject variability enters error term
             → sigma_total² ≈ 3×sigma_intra² (typical inter/intra ratio), hence much larger N
           - Required N typically 5–10× larger than crossover for same CVintra

        CRITICAL RULE: T½ > 24 hours → MUST choose Parallel design, NO EXCEPTIONS!

        **CRITICAL: You MUST respond in this EXACT format (no deviations):**

        DESIGN: [design name]
        N_SUBJECTS: [number]
        CV_INTRA: [CV% value used, number only]
        T_HALF: [T½ hours used, number only or N/A]

        REASONING:
        1. DATA SOURCES & QUALITY: [Which sources, reliability, concordance between sources, any concerns about extracted values]
        2. CVintra ANALYSIS: [Value, origin (extracted vs. assumed), variability category, regulatory implications for acceptance criteria]
        3. T½ ANALYSIS: [Value, calculated minimum washout (5×T½), whether crossover is practically feasible, carry-over risk]
        4. DESIGN SELECTION: [Why this design was chosen over alternatives; cite specific EAEU Decision 85 / FDA guidance criteria that apply]
        5. SAMPLE SIZE RATIONALE: [Why this N is appropriate; mention what would happen with alternative designs]

        **EXAMPLES:**

        Example 1 (Low variability, short T½ – standard crossover):
        DESIGN: 2×2 Cross-over
        N_SUBJECTS: 24
        CV_INTRA: 18.5
        T_HALF: 8.0

        REASONING:
        1. DATA SOURCES & QUALITY: CVintra was extracted from two independent PubMed BE studies reporting intrasubject variability of 17% and 20% respectively, showing good concordance. T½ = 8 hours confirmed by FDA label (authoritative source). No significant discrepancies between sources.
        2. CVintra ANALYSIS: CVintra = 18.5% (average of two consistent estimates). This falls in the low variability category (<30%), meaning standard 80.00–125.00% acceptance criteria apply per EAEU Decision 85. No widened criteria or replicated design are needed.
        3. T½ ANALYSIS: T½ = 8 hours. Minimum washout period = 5×8 = 40 hours (~1.7 days). In practice, a 7-day washout is typical, which is entirely feasible. No carry-over risk. Crossover design is fully appropriate.
        4. DESIGN SELECTION: Standard 2×2 crossover is the most efficient and well-established design for this PK profile. Per EAEU Decision 85 and FDA BE guidance, a 2-period, 2-sequence crossover is appropriate when CVintra < 30% and T½ < 24h. Each subject serves as their own control, eliminating between-subject variability from the error term and minimizing required N.
        5. SAMPLE SIZE RATIONALE: N = 24 is sufficient for CVintra = 18.5%, α = 0.05 (two-sided), 80% power, 80–125% limits. Parallel design would require ~5× more subjects (N ≈ 120) for the same power — clearly impractical when crossover is feasible.

        Example 2 (Moderate CVintra, long T½ – mandatory parallel):
        DESIGN: Параллельный
        N_SUBJECTS: 150
        CV_INTRA: 22.0
        T_HALF: 48.0

        REASONING:
        1. DATA SOURCES & QUALITY: T½ = 48 hours extracted from FDA label — the most authoritative source for absolute PK parameters. CVintra = 22% from one PubMed BE study; value is consistent with known pharmacology of this drug class. Data quality is acceptable, though a single CVintra source slightly limits confidence.
        2. CVintra ANALYSIS: CVintra = 22% places this drug in the low variability category (<30%). Under normal circumstances, this would support a 2×2 crossover design with standard 80–125% criteria. However, CVintra is not the determining factor here — T½ is.
        3. T½ ANALYSIS: T½ = 48 hours. Minimum washout = 5×48 = 240 hours = 10 days. In practice, regulatory guidelines require complete elimination before next dosing; with 48h T½, a realistic washout of 14–21 days would be needed. A 2-period crossover would span ≥ 6 weeks of inpatient monitoring, creating unacceptable dropout risk, ethical concerns, and logistical burden. Per FDA guidance and EAEU Decision 85, T½ > 24h renders crossover impractical.
        4. DESIGN SELECTION: Parallel-group design is mandatory (EAEU Decision 85; FDA Guidance for Industry – BE Studies with PK Endpoints, 2013). Crossover is contraindicated due to the excessively long required washout. Each subject receives only one product; no carry-over is possible. The statistical penalty is that all between-subject variability enters the error term (sigma_total² ≈ 3×sigma_intra²), requiring a much larger N.
        5. SAMPLE SIZE RATIONALE: N = 150 accounts for sigma_total² = 3×sigma_intra², delta = |ln(0.80)| = 0.2231, z_α/2 = 1.96, z_β = 0.842, and 20% dropout. A crossover at CVintra = 22% would need only N = 18 — but that option is ruled out by T½ > 24h. The large N is the unavoidable cost of the parallel design for a long-half-life drug.

        **CRITICAL RULES (MUST FOLLOW):**
        1. **T½ > 24 hours → ALWAYS use "Параллельный" design, NO EXCEPTIONS!**
        2. If CVintra not in data → use typical 20-25% and explicitly state this assumption in reasoning
        3. If T½ in data → check rule #1 FIRST before choosing design
        4. Use ONLY numbers for CV_INTRA and T_HALF (no units)
        5. Write REASONING in English. All 5 sections are mandatory. Be analytical, not just descriptive.

        **FORMAT REQUIREMENTS:**
        - DESIGN must be one of: "2×2 Cross-over", "3-way Replicate", "4-way Replicate", "Параллельный"
        - Field names (DESIGN:, N_SUBJECTS:, etc.) must be in English exactly as shown
        - REASONING sections must be numbered 1–5 exactly as shown"""

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

        # ── Интерпретация T½ ──────────────────────────────────────────────────
        t_half_info = ""
        if t_half_used:
            washout_h  = t_half_used * 5
            washout_d  = washout_h / 24
            t_half_info = (
                f"\n🕐 HALF-LIFE ANALYSIS:\n"
                f"   T½ = {t_half_used} hours\n"
                f"   Minimum washout (5×T½) = {washout_h:.0f} hours = {washout_d:.1f} days\n"
            )
            if t_half_used > 24:
                t_half_info += (
                    f"   ⚠️ T½ > 24h → if crossover were used, washout of ≥{washout_d:.0f} days would be required between periods.\n"
                    f"   Total crossover study duration would be ≥{washout_d * 2:.0f} days — impractical.\n"
                    f"   → PARALLEL DESIGN MANDATORY (per FDA guidance and EAEU Decision 85)\n"
                    f"   NOTE: Parallel design has NO washout period — each subject receives only ONE product.\n"
                    f"   The washout calculation above explains WHY crossover is ruled out, not a property of parallel design.\n"
                )
            else:
                t_half_info += f"   ✓ T½ < 24h → crossover washout is feasible ({washout_d:.1f} days)\n"

        # ── Интерпретация CVintra ─────────────────────────────────────────────
        cv_info = ""
        if cv_used:
            if cv_used < 30:
                cv_category = "LOW variability (<30%): standard 80–125% BE criteria apply; 2×2 crossover is sufficient"
                cv_implication = "2×2 Cross-over is the most efficient design. No need for replicated design or widened criteria."
            elif cv_used < 50:
                cv_category = "MODERATE-HIGH variability (30–50%): HVDP category; RSABE applicable"
                cv_implication = ("Replicated design (3-way or 4-way) enables reference-scaled Cmax criteria (widened to 69.84–143.19%), "
                                  "reducing required N significantly compared to parallel.")
            else:
                cv_category = "HIGH variability (>50%): highly variable drug; replicated design strongly indicated"
                cv_implication = "4-way replicated design with full RSABE is the most statistically powerful approach."
            cv_info = (
                f"\n📊 CVintra ANALYSIS:\n"
                f"   CVintra = {cv_used:.1f}%\n"
                f"   Category: {cv_category}\n"
                f"   Implication: {cv_implication}\n"
            )

        prompt = f"""{summary}{t_half_info}{cv_info}{sample_size_info}

            Based on this data and the regulatory framework provided:
            1. Choose the CVintra value to use (from data, or justify using typical ~22%)
            2. Apply the T½ rule FIRST: if T½ > 24h → Parallel is mandatory
            3. If crossover is feasible, select 2×2 / 3-way / 4-way based on CVintra
            4. Write REASONING in English with all 5 mandatory sections.
               Go beyond just stating numbers — explain the clinical and regulatory logic:
               - Why is the washout feasible or not? (show the 5×T½ calculation explicitly)
               - What does CVintra mean for the choice between standard vs. widened criteria?
               - What would happen if a different design were chosen? (compare alternatives)
               - Quote specific regulatory requirements that determine the decision.

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
