#!/usr/bin/env python3
"""
Главный скрипт для извлечения фармакокинетических данных
и рекомендации дизайна исследования биоэквивалентности.

Использование:
    python main.py --drug "Amlodipine" --form "tablet" --max-results 10
"""

import argparse
from typing import Optional
from extraction.pk_source import get_pk_data_from_all_sources
from models.design_recommender import DesignRecommender, print_recommendation, save_recommendation_to_json
from models.llm_config import get_llm_provider


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
    print("\n" + "="*80)
    print(f"🔬 АНАЛИЗ ПРЕПАРАТА: {drug}")
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

    # Сводка по найденным данным
    print("\n" + "="*80)
    print("📊 СВОДКА ПО НАЙДЕННЫМ ДАННЫМ")
    print("="*80)

    has_cmax = sum(1 for r in records if r.cmax)
    has_tmax = sum(1 for r in records if r.tmax)
    has_auc = sum(1 for r in records if r.auc)
    has_t_half = sum(1 for r in records if r.t_half)
    has_cv = sum(1 for r in records if r.cv_intra)

    print(f"\nВсего источников: {len(records)}")
    print(f"  ├─ с Cmax: {has_cmax}")
    print(f"  ├─ с Tmax: {has_tmax}")
    print(f"  ├─ с AUC: {has_auc}")
    print(f"  ├─ с T½: {has_t_half}")
    print(f"  └─ с CVintra: {has_cv} ⭐")

    # Показываем найденные CVintra (ключевой параметр!)
    if has_cv > 0:
        print("\n🎯 Найденные значения CVintra:")
        for r in records:
            if r.cv_intra:
                source_info = f"{r.study_id}" if r.study_id else r.source
                print(f"  • {r.cv_intra}% (источник: {source_info})")

    # Показываем T½ (важно для выбора дизайна)
    if has_t_half > 0:
        print("\n⏱️  Найденные значения T½:")
        for r in records:
            if r.t_half:
                source_info = f"{r.study_id}" if r.study_id else r.source
                unit = r.t_half_unit or "h"
                print(f"  • {r.t_half} {unit} (источник: {source_info})")

    # ========================================
    # ЭТАП 2: Рекомендация дизайна через LLM
    # ========================================
    print("\n" + "="*80)
    print("🤖 ЭТАП 2: Анализ данных и рекомендация дизайна")
    print("="*80 + "\n")

    # Получаем LLM провайдер из конфига
    llm_provider = get_llm_provider()

    # Создаём рекомендатор
    recommender = DesignRecommender(llm_provider)

    # Получаем рекомендацию
    try:
        recommendation = recommender.recommend_design(
            drug=drug,
            records=records,
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
Примеры использования:
  python main.py --drug "Amlodipine"
  python main.py --drug "Amlodipine" --form "tablet" --max-results 20
  python main.py --drug "Ibuprofen" --form "capsule"

Настройка LLM:
  Отредактируйте файл llm_config.py для выбора модели (Claude, OpenAI, Ollama и т.д.)
        """
    )

    parser.add_argument(
        "--drug",
        type=str,
        required=True,
        help="Название препарата (INN)"
    )

    parser.add_argument(
        "--form",
        type=str,
        default=None,
        help="Форма выпуска (tablet, capsule, solution и т.д.)"
    )

    parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Максимальное количество статей для анализа (по умолчанию: 10)"
    )

    args = parser.parse_args()

    # Запускаем анализ
    analyze_drug(
        drug=args.drug,
        dosage_form=args.form,
        max_results=args.max_results
    )


if __name__ == "__main__":
    main()
