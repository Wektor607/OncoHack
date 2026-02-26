#!/usr/bin/env python3
"""
Главный скрипт для извлечения фармакокинетических данных
и рекомендации дизайна исследования биоэквивалентности.

Использование:
    python main.py --drug "Amlodipine" --form "tablet" --max-results 10
"""

import argparse
import os
import sys
from pathlib import Path
from typing import Optional
from extraction.pk_source import get_pk_data_from_all_sources, normalize_inn, merge_pk_records
from extraction.sample_size import calculate_washout_period
from models.design_recommender import DesignRecommender, print_recommendation, save_recommendation_to_json
from models.llm_config import get_llm_provider, get_translate_provider
from generate_synopsis import fill_template

TEMPLATE_PATH = "synopsis_template.docx"

def analyze_drug(
    drug: str,
    dosage_form: Optional[str] = None,
    max_results: int = 10
):
    """
    Полный анализ препарата: извлечение данных + рекомендация дизайна.

    Args:
        drug: Название препарата (INN)
        dosage_form: Форма выпуска (tablet, capsule, и т.д.)
        max_results: Максимальное количество статей для анализа
    """
    # Нормализуем ИНН: локальный словарь → GRLS → RxNorm
    inn = normalize_inn(drug)
    if inn.lower() != drug.lower():
        print(f"\n💡 ИНН нормализован: «{drug}» → «{inn}»")
    drug = inn

    print("\n" + "="*80)
    print(f"🔬 АНАЛИЗ ПРЕПАРАТА (ИНН): {drug}")
    if dosage_form:
        print(f"💊 Форма выпуска: {dosage_form}")
    print("="*80 + "\n")

    # ========================================
    # ЭТАП 1: Извлечение данных из источников
    # ========================================
    print("📚 ЭТАП 1: Извлечение фармакокинетических данных")
    print("-" * 80)

    records = get_pk_data_from_all_sources(
        drug=drug,
        dosage_form=dosage_form,
        max_results=max_results
    )

    if not records:
        print("❌ Данные не найдены. Попробуйте другой препарат или увеличьте max_results.")
        return

    # ==========================================
    # Агрегация: объединяем все записи в одну
    # ==========================================
    merged = merge_pk_records(records, drug)

    # Сводка по найденным данным
    print("\n" + "="*80)
    print("📊 СВОДКА ПО НАЙДЕННЫМ ДАННЫМ")
    print("="*80)

    has_cmax  = sum(1 for r in records if r.cmax)
    has_tmax  = sum(1 for r in records if r.tmax)
    has_auc   = sum(1 for r in records if r.auc)
    has_t_half= sum(1 for r in records if r.t_half)
    has_cv    = sum(1 for r in records if r.cv_intra)

    print(f"\nВсего источников: {len(records)}")
    print(f"  ├─ с Cmax:    {has_cmax}")
    print(f"  ├─ с Tmax:    {has_tmax}")
    print(f"  ├─ с AUC:     {has_auc}")
    print(f"  ├─ с T½:      {has_t_half}")
    print(f"  └─ с CVintra: {has_cv} ⭐")

    # Показываем CVintra по каждому источнику
    if has_cv > 0:
        print("\n🎯 CVintra по источникам:")
        for r in records:
            if r.cv_intra:
                source_info = r.study_id or r.source
                cv_src = r.cv_intra_source or "extracted"
                if cv_src == "calculated_from_ci":
                    ci_info = f" [рассчитан из 90% ДИ: {r.ci_lower:.3f}–{r.ci_upper:.3f}, n={r.n_subjects}]"
                elif cv_src == "database":
                    ci_info = " [из базы типичных значений]"
                else:
                    ci_info = " [извлечён из статьи]"
                print(f"  • {r.cv_intra}% ({source_info}){ci_info}")

    # Показываем T½ по источникам
    if has_t_half > 0:
        print("\n⏱️  T½ по источникам:")
        for r in records:
            if r.t_half:
                source_info = r.study_id or r.source
                unit = r.t_half_unit or "h"
                print(f"  • {r.t_half} {unit} ({source_info})")

    # Итоговая объединённая запись
    print("\n" + "─"*80)
    print("🔗 ОБЪЕДИНЁННЫЕ ДАННЫЕ (используются для рекомендации):")
    if merged.cmax:    print(f"  Cmax:    {merged.cmax} {merged.cmax_unit or ''}")
    if merged.tmax:    print(f"  Tmax:    {merged.tmax} {merged.tmax_unit or ''}")
    if merged.auc:     print(f"  AUC:     {merged.auc} {merged.auc_unit or ''}")
    if merged.t_half:
        print(f"  T½:      {merged.t_half} {merged.t_half_unit or 'h'}")
        washout = calculate_washout_period(merged.t_half)
        print(f"  Washout: {washout['washout_rec_h']}ч ({washout['washout_rec_days']} сут) "
              f"[5–6 × T½, рек. {washout['washout_min_h']}–{washout['washout_max_h']}ч]")
        if washout['is_parallel_required']:
            print(f"  ⚠️  T½ > 24ч → рекомендуется параллельный дизайн!")
    if merged.cv_intra:
        cv_src = merged.cv_intra_source or ""
        src_label = {
            "extracted":         "[извлечён из статьи]",
            "calculated_from_ci":"[рассчитан из 90% ДИ]",
            "database":          "[из базы типичных значений]",
        }.get(cv_src, "")
        cv_detail = ""
        if merged.cv_intra_auc and merged.cv_intra_cmax:
            cv_detail = f" (AUC={merged.cv_intra_auc}%, Cmax={merged.cv_intra_cmax}%, взят max)"
        elif merged.cv_intra_auc:
            cv_detail = f" (по AUC)"
        elif merged.cv_intra_cmax:
            cv_detail = f" (по Cmax)"
        print(f"  CVintra: {merged.cv_intra}% {src_label}{cv_detail}")
    print("─"*80)

    # ========================================
    # ЭТАП 2: Рекомендация дизайна через LLM
    # ========================================
    print("\n" + "="*80)
    print("🤖 ЭТАП 2: Анализ данных и рекомендация дизайна")
    print("="*80 + "\n")

    llm = get_llm_provider()
    translate_llm = get_translate_provider()

    # Создаём рекомендатор; передаём merged как первый элемент
    # (чтобы LLM видел лучшие данные из всех источников)
    recommender = DesignRecommender(llm, translate_provider=translate_llm)
    # merged первым — LLM получает лучшие агрегированные данные
    records_for_llm = [merged] + records

    # Получаем рекомендацию
    recommendation = None
    try:
        recommendation = recommender.recommend_design(
            drug=drug,
            records=records_for_llm,
            dosage_form=dosage_form
        )

        # Выводим результат
        print_recommendation(recommendation)

        # Сохраняем результат в файлы (текст и JSON)
        save_recommendation_to_file(drug, recommendation, records)

        # Сохраняем JSON
        json_filename = f"recommendation_{drug.lower().replace(' ', '_')}.json"
        save_recommendation_to_json(recommendation, json_filename)

    except Exception as e:
        print(f"❌ Ошибка при получении рекомендации: {e}")
        import traceback
        traceback.print_exc()
    
    return recommendation, records


def save_recommendation_to_file(drug: str, recommendation: dict, records: list):
    """Сохраняет рекомендацию в текстовый файл."""
    filename = f"recommendation_{drug.lower().replace(' ', '_')}.txt"

    with open(filename, "w", encoding="utf-8") as f:
        f.write("="*80 + "\n")
        f.write(f"РЕКОМЕНДАЦИЯ ПО ДИЗАЙНУ ИССЛЕДОВАНИЯ: {drug}\n")
        f.write("="*80 + "\n\n")

        f.write(f"Дизайн: {recommendation['design']}\n")
        f.write(f"Количество участников: {recommendation['n_subjects']}\n")

        if recommendation['cv_intra_used']:
            f.write(f"CVintra (использовано): {recommendation['cv_intra_used']}%\n")

        if recommendation['t_half_used']:
            f.write(f"T½ (использовано): {recommendation['t_half_used']} часов\n")

        f.write("\nОБОСНОВАНИЕ:\n")
        f.write("-" * 80 + "\n")
        f.write(recommendation['reasoning'] + "\n")

        f.write("\n\nИСТОЧНИКИ ДАННЫХ:\n")
        f.write("-" * 80 + "\n")
        for i, r in enumerate(records, 1):
            f.write(f"\n{i}. {r.source}")
            if r.study_id:
                f.write(f" (ID: {r.study_id})")
            if r.title:
                f.write(f"\n   {r.title}")
            f.write("\n")

    print(f"\n💾 Результаты сохранены в файл: {filename}")


def main():
    """Точка входа в программу."""
    parser = argparse.ArgumentParser(
        description="Анализ препарата и рекомендация дизайна исследования биоэквивалентности",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры ИНН (один ИНН = один уникальный препарат):
  Кардио:        amlodipine, valsartan, losartan, bisoprolol, atorvastatin
  Диабет:        metformin, glimepiride, sitagliptin
  НПВС:          ibuprofen, diclofenac, meloxicam
  Антибиотики:   azithromycin, ciprofloxacin, amoxicillin
  Иммунно:       tacrolimus, cyclosporine  (высокая вариабельность)
  ИПП:           omeprazole, pantoprazole
  Антикоаг.:     warfarin, rivaroxaban, apixaban

Примеры вызова:
  python main.py --drug "amlodipine"
  python main.py --drug "metformin" --form "tablet" --max-results 20
  python main.py --drug "tacrolimus" --form "capsule"

Также принимаются торговые/дженерические названия (будет выполнен поиск ИНН через GRLS/RxNorm):
  python main.py --drug "Амлодипин-Тева"

Настройка LLM:
  Отредактируйте файл .env или llm_config.py (Claude, OpenAI, Ollama и т.д.)
        """
    )

    # INN
    parser.add_argument(
        "--drug",
        type=str,
        required=True,
        help="ИНН препарата (INN) — один ИНН соответствует одному препарату. "
            "Примеры: amlodipine, metformin, atorvastatin, tacrolimus"
    )

    # Форма выпуска
    parser.add_argument(
        "--form",
        type=str,
        default=None,
        choices=[
            "tablet", "capsule", "solution", "suspension", "powder",
            "injection", "cream", "ointment", "patch", "spray", "drops", "other"
        ],
        help="Форма выпуска (tablet, capsule, solution и т.д.)"
    )

    # Дозировка/доза (если нужно различать strength vs dose — можно оставить оба)
    parser.add_argument(
        "--strength",
        type=float,
        default=None,
        help="Сила дозировки (число), напр. 5 для '5 mg'"
    )
    parser.add_argument(
        "--strength-unit",
        type=str,
        default="mg",
        choices=["mg", "g", "mcg", "ug", "ng", "IU", "mL"],
        help="Единицы для strength (по умолчанию: mg)"
    )

    parser.add_argument(
        "--dosing",
        type=str,
        default="однократный",
        choices=["однократный", "многократный"],
        help="Режим дозирования: однократный/многократный"
    )

    parser.add_argument(
        "--dose_number",
        type=float,
        default=None,
        help="Разовая доза (число), напр. 10 для '10 mg'"
    )
    parser.add_argument(
        "--dose-unit",
        type=str,
        default="mg",
        choices=["mg", "g", "mcg", "ug", "ng", "IU", "mL"],
        help="Единицы для dose (по умолчанию: mg)"
    )

    # Внутрисубъектная вариабельность
    parser.add_argument(
        "--isv",
        type=str,
        default="auto",
        choices=["low", "high", "auto", "unknown"],
        help="Предполагаемая внутрисубъектная вариабельность: low/high/auto/unknown (по умолчанию: auto)"
    )
    parser.add_argument(
        "--isv-cv",
        type=float,
        default=None,
        help="Если известен CV% (внутрисубъектный), укажи числом, например 35.0"
    )

    # RSABE
    parser.add_argument(
        "--rsabe",
        type=str,
        default="auto",
        choices=["yes", "no", "auto"],
        help="Нужно ли применять RSABE: yes/no/auto (по умолчанию: auto)"
    )

    # Предпочтительный дизайн
    parser.add_argument(
        "--design",
        type=str,
        default="auto",
        choices=["auto", "crossover_2x2", "replicate_partial", "replicate_full", "parallel", "other"],
        help="Предпочтительный дизайн исследования (по умолчанию: auto)"
    )
    parser.add_argument(
        "--design-notes",
        type=str,
        default=None,
        help="Комментарий к дизайну (если design=other или есть доп. пожелания)"
    )

    # Режим приёма
    parser.add_argument(
        "--fed-state",
        type=str,
        default="натощак/после приема пищи",
        choices=["натощак", "после приема высококалорийной пищи", "оба варианта"],
        help="Режим приёма: натощак/после приема пищи/оба варианта"
    )
    parser.add_argument(
        "--meal-type",
        type=str,
        default=None,
        choices=["high_fat_high_calorie", "standard", "unspecified", "other"],
        help="Тип еды (если fed): high_fat_high_calorie/standard/unspecified/other"
    )

    # Тип исследования
    parser.add_argument(
        "--study-type",
        type=str,
        default="model_selected",
        choices=["single_phase", "two_phase", "model_selected"],
        help="Тип исследования: single_phase/two_phase/model_selected (по умолчанию: model_selected)"
    )

    # Доп. требования заказчика: пол / возраст / прочие ограничения
    parser.add_argument(
        "--sex",
        type=str,
        default="any",
        choices=["male_only", "female_only", "mixed", "any"],
        help="Гендерный состав: male_only/female_only/mixed/any (по умолчанию: any)"
    )
    parser.add_argument(
        "--age-min",
        type=int,
        default=None,
        help="Минимальный возраст участников (лет)"
    )
    parser.add_argument(
        "--age-max",
        type=int,
        default=None,
        help="Максимальный возраст участников (лет)"
    )
    parser.add_argument(
        "--constraints",
        type=str,
        nargs="*",
        default=None,
        help="Прочие ограничения (списком), напр: --constraints \"healthy volunteers\" \"non-smokers\""
    )

    # У тебя уже есть
    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Максимальное количество статей для анализа (по умолчанию: 10)"
    )

    args = parser.parse_args()
    os.makedirs("outputs", exist_ok=True)
    # Запускаем анализ
    recommendation, records = analyze_drug(
        drug=args.drug,
        dosage_form=args.form,
        max_results=args.max_results
    )

    json_file = f"outputs/recommendation_{args.drug}.json"
    out_file  = f"outputs/synopsis_{args.drug}.docx"

    if recommendation is None:
        print("❌ Рекомендация не получена, синопсис не генерируется.")
        sys.exit(1)

    if not Path(json_file).exists():
        print(f"Файл не найден: {json_file}")
        sys.exit(1)
    if not Path(template_path := TEMPLATE_PATH).exists():
        print(f"Шаблон не найден: {template_path}")
        sys.exit(1)

    design_synopsis = recommendation.get('design_synopsis') or recommendation.get('reasoning', '')
    fill_template(args, json_file, out_file, TEMPLATE_PATH, design_synopsis, records=records)

if __name__ == "__main__":
    main()
