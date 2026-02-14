"""
Модуль для расчёта размера выборки для исследований биоэквивалентности.

Формулы основаны на стандартных методах:
- 2×2 Cross-over: N = 2(Z_α + Z_β)² σ² / (ln Θ₁)²
- 3-way Replicate: N = 3(Z_α + Z_β)² σ² / (ln Θ₁)²
- 4-way Replicate (RSABE): N = 4(Z_α + Z_β)² σ² / (ln Θ₁)²
- Параллельный: N = 4(Z_α + Z_β)² σ² / δ²

где σ² = (ln(1 + CV))² - внутрисубъектная дисперсия
"""

import math
from typing import Dict, Optional

# Таблица критических значений стандартного нормального распределения
# Для использования без scipy
Z_TABLE = {
    0.90: 1.2816,  # 90% мощность
    0.80: 0.8416,  # 80% мощность
    0.95: 1.6449,  # 95% мощность
    0.975: 1.9600, # для alpha=0.05 (двусторонний)
    0.99: 2.3263,  # для alpha=0.01 (двусторонний)
}

def get_z_value(probability: float) -> float:
    """Возвращает Z-значение для заданной вероятности."""
    if probability in Z_TABLE:
        return Z_TABLE[probability]

    # Если точного значения нет, используем приближение
    # Для более точных значений нужна scipy
    closest = min(Z_TABLE.keys(), key=lambda x: abs(x - probability))
    return Z_TABLE[closest]


def calculate_sample_size(
    design: str,
    cv_intra: float,
    alpha: float = 0.05,
    power: float = 0.80,
    theta1: float = 0.80,
    theta2: float = 1.25,
    dropout_rate: float = 0.20
) -> Dict:
    """
    Рассчитывает размер выборки для исследования биоэквивалентности.

    Args:
        design: Тип дизайна ("2×2 Cross-over", "3-way Replicate", "4-way Replicate", "Параллельный")
        cv_intra: Внутрииндивидуальная вариабельность (%)
        alpha: Уровень значимости (по умолчанию 0.05 для двустороннего теста)
        power: Мощность теста (по умолчанию 0.80)
        theta1: Нижняя граница биоэквивалентности (по умолчанию 0.80)
        theta2: Верхняя граница биоэквивалентности (по умолчанию 1.25)
        dropout_rate: Процент выбывания участников (по умолчанию 20%)

    Returns:
        Dict с результатами расчёта:
        {
            "n_per_sequence": int,  # Количество участников на последовательность
            "n_total": int,  # Общее количество участников (без dropout)
            "n_with_dropout": int,  # С учётом выбывания
            "formula_used": str,
            "parameters": dict,
            "reasoning": str
        }
    """
    # Преобразуем CV из % в коэффициент (25% → 0.25)
    cv = cv_intra / 100.0

    # Вычисляем σ² (внутрисубъектную дисперсию)
    # Формула: σ² = (ln(1 + CV))²
    # Например: CV = 25% = 0.25 → σ² = (ln(1 + 0.25))² = (ln(1.25))² = (0.223)² = 0.0497
    sigma_squared = (math.log(1 + cv)) ** 2  # ВАЖНО: сначала ln(1+CV), потом возводим в квадрат!

    # Z-значения (критические значения стандартного нормального распределения)
    # Z_α/2 - для двустороннего теста с уровнем значимости α = 0.05 → Z = 1.96
    z_alpha = get_z_value(1 - alpha/2)

    # Z_β - для мощности power = 0.80 (т.е. β = 0.20) → Z = 0.84
    z_beta = get_z_value(power)

    # ln(Θ₁) - натуральный логарифм нижней границы биоэквивалентности
    # Θ₁ = 0.80 → ln(0.80) = -0.223
    ln_theta1 = math.log(theta1)

    # Расчёт базового размера выборки в зависимости от дизайна
    if "2×2" in design or "2x2" in design.lower() or "cross-over" in design.lower():
        # N = 2(Z_α + Z_β)² σ² / (ln Θ₁)²
        n_base = 2 * ((z_alpha + z_beta)**2) * sigma_squared / (ln_theta1**2)
        formula = "N = 2(Z_α + Z_β)² × σ² / (ln Θ₁)²"
        sequences = 2

    elif "3-way" in design.lower() or "3-период" in design.lower():
        # N = 3(Z_α + Z_β)² σ² / (ln Θ₁)²
        n_base = 3 * ((z_alpha + z_beta)**2) * sigma_squared / (ln_theta1**2)
        formula = "N = 3(Z_α + Z_β)² × σ² / (ln Θ₁)²"
        sequences = 2

    elif "4-way" in design.lower():
        # N = 2(Z_α + Z_β)² σ² / (ln Θ₁)²
        n_base = 2 * ((z_alpha + z_beta)**2) * sigma_squared / (ln_theta1**2)
        formula = "N = 2(Z_α + Z_β)² × σ² / (ln Θ₁)²"
        sequences = 2
    # elif "rsabe" in design.lower():
    #     # N = 2(Z_α + Z_β)² / k²
    #     k = 0.760
    #     n_base = 2 * (z_alpha + z_beta)**2 / (k**2)
    #     formula = "N = 2(Zα + Zβ)² / k²  (RSABE)"
    #     sequences = 2
    elif "параллельный" in design.lower() or "parallel" in design.lower():
        # N = 2(Z_α + Z_β)² σ² / δ²
        # Для параллельного дизайна используем δ = ln(theta2) - ln(theta1)
        delta = math.log(theta2) - math.log(theta1)
        n_base = 2 * ((z_alpha + z_beta)**2) * sigma_squared / (delta**2)
        formula = "N = 2(Z_α + Z_β)² × σ² / δ²"
        sequences = 2

    else:
        # По умолчанию используем 2×2
        n_base = 2 * ((z_alpha + z_beta)**2) * sigma_squared / (ln_theta1**2)
        formula = "N = 2(Z_α + Z_β)² × σ² / (ln Θ₁)²"
        sequences = 2

    # --- Округление без dropout ---

    if "parallel" in design.lower() or "параллельный" in design.lower():
        # n_base уже total
        n_total = math.ceil(n_base / 2) * 2  # делаем группы равными
    else:
        # crossover / replicate
        n_total = math.ceil(n_base / sequences) * sequences

    # --- С учётом dropout ---
    n_with_dropout = math.ceil(n_total / (1 - dropout_rate))

    # снова обеспечиваем кратность последовательностям
    if "parallel" in design.lower() or "параллельный" in design.lower():
        n_with_dropout = math.ceil(n_with_dropout / 2) * 2
    else:
        n_with_dropout = math.ceil(n_with_dropout / sequences) * sequences

    # распределение по последовательностям
    n_per_sequence = n_total // sequences

    # Формируем обоснование
    reasoning = f"""Расчёт размера выборки для исследования биоэквивалентности:

        1. Исходные параметры:
        • CVintra = {cv_intra}%
        • α (уровень значимости) = {alpha} (двусторонний тест)
        • Power (мощность) = {power} ({int(power*100)}%)
        • Границы биоэквивалентности: {theta1:.2f} - {theta2:.2f}
        • Ожидаемое выбывание: {int(dropout_rate*100)}%

        2. Критические значения:
        • Z_α/2 = {z_alpha:.4f} (квантиль стандартного нормального распределения для α/2 = {alpha/2})
        • Z_β = {z_beta:.4f} (квантиль для мощности {int(power*100)}%)

        3. Расчёт дисперсии:
        • σ² = (ln(1 + CV))² = (ln(1 + {cv:.4f}))² = (ln({1+cv:.4f}))²
        • σ² = ({math.log(1+cv):.4f})² = {sigma_squared:.6f}

        4. Расчёт ln(Θ₁):
        • ln(Θ₁) = ln({theta1}) = {ln_theta1:.4f}
        • (ln Θ₁)² = {ln_theta1**2:.6f}

        5. Применение формулы:
        {formula}

        N = {n_base:.2f} ≈ {n_total} участников

        6. Учёт выбывания:
        • Базовый размер: {n_total} участников
        • С учётом {int(dropout_rate*100)}% dropout: {n_total} / {1-dropout_rate:.2f} = {n_with_dropout} участников

        Рекомендация: Набрать {n_with_dropout} участников для обеспечения {int(power*100)}% мощности исследования
        при уровне значимости {int((1-alpha)*100)}% и ожидаемом выбывании {int(dropout_rate*100)}%."""

    return {
        "n_per_sequence": n_per_sequence,
        "n_total": n_total,
        "n_with_dropout": n_with_dropout,
        "formula_used": formula,
        "parameters": {
            "cv_intra": cv_intra,
            "alpha": alpha,
            "power": power,
            "theta1": theta1,
            "theta2": theta2,
            "dropout_rate": dropout_rate,
            "z_alpha": round(z_alpha, 4),
            "z_beta": round(z_beta, 4),
            "sigma_squared": round(sigma_squared, 6),
            "ln_theta1": round(ln_theta1, 4)
        },
        "reasoning": reasoning
    }


# def get_recommended_design_parameters(cv_intra: float, t_half: Optional[float] = None) -> Dict:
#     """
#     Рекомендует дизайн и параметры исследования на основе CVintra и T½.

#     Args:
#         cv_intra: Внутрииндивидуальная вариабельность (%)
#         t_half: Период полувыведения (часы), опционально

#     Returns:
#         Dict с рекомендацией:
#         {
#             "design": str,
#             "reasoning": str,
#             "typical_n": int
#         }
#     """
#     # Проверяем T½ для параллельного дизайна
#     if t_half and t_half > 24:
#         return {
#             "design": "Параллельный",
#             "reasoning": f"Период полувыведения T½ = {t_half} часов превышает 24 часа, что делает перекрёстный дизайн непрактичным из-за длительного washout периода.",
#             "typical_n": 150
#         }

#     # Выбор дизайна на основе CVintra
#     if cv_intra <= 30:
#         return {
#             "design": "2×2 Cross-over",
#             "reasoning": f"CVintra = {cv_intra}% ≤ 30% указывает на низкую вариабельность препарата. Стандартный дизайн 2×2 Cross-over является оптимальным.",
#             "typical_n": 24
#         }
#     elif cv_intra <= 50:
#         return {
#             "design": "3-way Replicate",
#             "reasoning": f"CVintra = {cv_intra}% находится в диапазоне 30-50%, что указывает на средневариабельный препарат. Рекомендуется дизайн 3-way Replicate с повторными измерениями.",
#             "typical_n": 36
#         }
#     else:
#         return {
#             "design": "4-way Replicate (RSABE)",
#             "reasoning": f"CVintra = {cv_intra}% > 50% указывает на высоковариабельный препарат. Требуется дизайн 4-way Replicate с применением RSABE (Reference-Scaled Average Bioequivalence).",
#             "typical_n": 48
#         }


# Пример использования
if __name__ == "__main__":
    # Пример 1: Низковариабельный препарат (из изображения)
    print("=" * 80)
    print("ПРИМЕР 1: CVintra = 25%")
    print("=" * 80)

    result = calculate_sample_size(
        design="2×2 Cross-over",
        cv_intra=25.0,
        alpha=0.05,
        power=0.80,
        dropout_rate=0.20
    )

    print(f"\nДизайн: 2×2 Cross-over")
    print(f"Размер выборки (базовый): {result['n_total']} участников")
    print(f"Размер выборки (с 20% dropout): {result['n_with_dropout']} участников")
    print(f"\nФормула: {result['formula_used']}")
    print(f"\nПараметры расчёта:")
    print(f"  Z_α/2 = {result['parameters']['z_alpha']}")
    print(f"  Z_β = {result['parameters']['z_beta']}")
    print(f"  σ² = {result['parameters']['sigma_squared']}")
    print(f"  ln(Θ₁) = {result['parameters']['ln_theta1']}")

    # Пример 2: Высоковариабельный препарат
    print("\n" + "=" * 80)
    print("ПРИМЕР 2: CVintra = 55%")
    print("=" * 80)

    result = calculate_sample_size(
        design="4-way Replicate (RSABE)",
        cv_intra=55.0,
        alpha=0.05,
        power=0.80,
        dropout_rate=0.25
    )

    print(f"\nДизайн: 4-way Replicate (RSABE)")
    print(f"Размер выборки (базовый): {result['n_total']} участников")
    print(f"Размер выборки (с 25% dropout): {result['n_with_dropout']} участников")
    print(f"\nФормула: {result['formula_used']}")
