from dataclasses import dataclass
from typing import Optional

@dataclass
class PKRecord:
    source: str
    drug: str

    # Входные параметры (из картинки 3)
    dosage_form: Optional[str] = None  # форма выпуска
    dosage: Optional[float] = None  # дозировка
    dosage_unit: Optional[str] = None
    dosing_regimen: Optional[str] = None  # режим приёма

    # Фармакокинетические параметры (из картинки 2)
    cmax: Optional[float] = None
    cmax_unit: Optional[str] = None

    tmax: Optional[float] = None  # ДОБАВЛЕНО
    tmax_unit: Optional[str] = None

    auc: Optional[float] = None
    auc_unit: Optional[str] = None

    t_half: Optional[float] = None
    t_half_unit: Optional[str] = None

    clearance: Optional[float] = None  # ДОБАВЛЕНО
    clearance_unit: Optional[str] = None

    volume_distribution: Optional[float] = None  # ДОБАВЛЕНО (Vd)
    vd_unit: Optional[str] = None

    cv_intra: Optional[float] = None  # вариабельность (%) — max(AUC, Cmax) по ЕАЭС
    cv_intra_source: Optional[str] = None  # "extracted" | "calculated_from_ci" | "database"
    cv_intra_auc: Optional[float] = None   # CVintra по AUC (%)
    cv_intra_cmax: Optional[float] = None  # CVintra по Cmax (%)

    # 90% ДИ отношения геометрических средних (для расчёта CVintra)
    ci_lower: Optional[float] = None   # нижняя граница 90% ДИ (как отношение, напр. 0.85)
    ci_upper: Optional[float] = None   # верхняя граница 90% ДИ (как отношение, напр. 1.18)

    # Метаданные исследования
    title: Optional[str] = None  # Название статьи/исследования
    design: Optional[str] = None  # Обнаруженный дизайн в статье
    n_subjects: Optional[int] = None
    study_id: Optional[str] = None  # PMID, DrugBank ID и т.д.

    # Рекомендуемый дизайн для биоэквивалентности (автоматически)
    recommended_design: Optional[str] = None
    recommended_n: Optional[int] = None
    design_reasoning: Optional[str] = None

    # Значения, отклонённые при извлечении (для диагностики)
    rejected_params: Optional[list] = None
