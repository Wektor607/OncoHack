import json
import math
import re

import requests
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from .pk_record import PKRecord


# =============================================================================
# ИНН-РЕЗОЛВЕР: торговое/генерическое название → стандартный ИНН (INN)
# Источники (в порядке приоритета):
#   1. Локальный словарь (_INN_LOCAL) — быстро, без сети
#   2. GRLS (Государственный реестр лекарственных средств РФ) — для дженериков
#   3. RxNorm (NLM USA) — международная база
# =============================================================================

# Локальный словарь: ключ — любое написание, значение — ИНН по ВОЗ
# Примеры ИНН (один ИНН = один препарат): amlodipine, metformin, atorvastatin
_INN_LOCAL: dict[str, str] = {
    # Блокаторы кальциевых каналов
    "amlodipine": "amlodipine", "амлодипин": "amlodipine",
    "nifedipine": "nifedipine", "нифедипин": "nifedipine",
    "felodipine": "felodipine", "фелодипин": "felodipine",
    "verapamil":  "verapamil",  "верапамил": "verapamil",
    "diltiazem":  "diltiazem",  "дилтиазем": "diltiazem",
    "lercanidipine": "lercanidipine", "лерканидипин": "lercanidipine",
    # БРА
    "valsartan":    "valsartan",  "валсартан":   "valsartan",
    "losartan":     "losartan",   "лозартан":    "losartan",
    "telmisartan":  "telmisartan","телмисартан": "telmisartan",
    "irbesartan":   "irbesartan", "ирбесартан":  "irbesartan",
    "olmesartan":   "olmesartan", "олмесартан":  "olmesartan",
    "candesartan":  "candesartan","кандесартан": "candesartan",
    # иАПФ
    "enalapril":  "enalapril",  "эналаприл": "enalapril",
    "lisinopril": "lisinopril", "лизиноприл":"lisinopril",
    "ramipril":   "ramipril",   "рамиприл":  "ramipril",
    "perindopril":"perindopril","периндоприл":"perindopril",
    "captopril":  "captopril",  "каптоприл": "captopril",
    # Бета-блокаторы
    "metoprolol": "metoprolol", "метопролол":"metoprolol",
    "bisoprolol": "bisoprolol", "бисопролол":"bisoprolol",
    "carvedilol": "carvedilol", "карведилол":"carvedilol",
    "atenolol":   "atenolol",   "атенолол":  "atenolol",
    "nebivolol":  "nebivolol",  "небиволол": "nebivolol",
    # Статины
    "atorvastatin": "atorvastatin","аторвастатин":"atorvastatin",
    "rosuvastatin": "rosuvastatin","розувастатин":"rosuvastatin",
    "simvastatin":  "simvastatin", "симвастатин": "simvastatin",
    "pravastatin":  "pravastatin", "правастатин": "pravastatin",
    # Сахароснижающие
    "metformin":   "metformin",   "метформин":  "metformin",
    "glibenclamide":"glibenclamide","глибенкламид":"glibenclamide",
    "glimepiride": "glimepiride", "глимепирид": "glimepiride",
    "sitagliptin": "sitagliptin", "ситаглиптин":"sitagliptin",
    # НПВС
    "ibuprofen":  "ibuprofen",  "ибупрофен": "ibuprofen",
    "diclofenac": "diclofenac", "диклофенак":"diclofenac",
    "naproxen":   "naproxen",   "напроксен":  "naproxen",
    "meloxicam":  "meloxicam",  "мелоксикам":"meloxicam",
    "celecoxib":  "celecoxib",  "целекоксиб":"celecoxib",
    # Антибиотики
    "azithromycin":   "azithromycin",   "азитромицин":  "azithromycin",
    "ciprofloxacin":  "ciprofloxacin",  "ципрофлоксацин":"ciprofloxacin",
    "amoxicillin":    "amoxicillin",    "амоксициллин": "amoxicillin",
    "levofloxacin":   "levofloxacin",   "левофлоксацин":"levofloxacin",
    "clarithromycin": "clarithromycin", "кларитромицин":"clarithromycin",
    "doxycycline":    "doxycycline",    "доксициклин":  "doxycycline",
    # Иммуносупрессанты
    "tacrolimus":   "tacrolimus",   "такролимус":  "tacrolimus",
    "cyclosporine": "cyclosporine", "циклоспорин": "cyclosporine",
    "sirolimus":    "sirolimus",    "сиролимус":   "sirolimus",
    "everolimus":   "everolimus",   "эверолимус":  "everolimus",
    # Антикоагулянты
    "warfarin":    "warfarin",    "варфарин":   "warfarin",
    "rivaroxaban": "rivaroxaban", "ривароксабан":"rivaroxaban",
    "apixaban":    "apixaban",    "апиксабан":  "apixaban",
    "dabigatran":  "dabigatran",  "дабигатран": "dabigatran",
    # ИПП
    "omeprazole":   "omeprazole",  "омепразол":  "omeprazole",
    "pantoprazole": "pantoprazole","пантопразол":"pantoprazole",
    "esomeprazole": "esomeprazole","эзомепразол":"esomeprazole",
    "lansoprazole": "lansoprazole","лансопразол":"lansoprazole",
    # Прочие
    "montelukast":    "montelukast",    "монтелукаст":   "montelukast",
    "levothyroxine":  "levothyroxine",  "левотироксин":  "levothyroxine",
    "clopidogrel":    "clopidogrel",    "клопидогрел":   "clopidogrel",
    "furosemide":     "furosemide",     "фуросемид":     "furosemide",
    "spironolactone": "spironolactone", "спиронолактон": "spironolactone",
    "acetylsalicylic acid": "acetylsalicylic acid",
    "aspirin": "acetylsalicylic acid",  "аспирин": "acetylsalicylic acid",
    # Онкология
    "axitinib":     "axitinib",     "акситиниб":    "axitinib",
    "imatinib":     "imatinib",     "иматиниб":     "imatinib",
    "erlotinib":    "erlotinib",    "эрлотиниб":    "erlotinib",
    "gefitinib":    "gefitinib",    "гефитиниб":    "gefitinib",
    "sorafenib":    "sorafenib",    "сорафениб":    "sorafenib",
    "sunitinib":    "sunitinib",    "сунитиниб":    "sunitinib",
    "lapatinib":    "lapatinib",    "лапатиниб":    "lapatinib",
    "cabozantinib": "cabozantinib", "кабозантиниб": "cabozantinib",
    "lenvatinib":   "lenvatinib",   "ленватиниб":   "lenvatinib",
    "regorafenib":  "regorafenib",  "регорафениб":  "regorafenib",
    "pazopanib":    "pazopanib",    "пазопаниб":    "pazopanib",
    "vandetanib":   "vandetanib",   "вандетаниб":   "vandetanib",
    "dasatinib":    "dasatinib",    "дазатиниб":    "dasatinib",
    "nilotinib":    "nilotinib",    "нилотиниб":    "nilotinib",
    "bosutinib":    "bosutinib",    "бозутиниб":    "bosutinib",
    "ponatinib":    "ponatinib",    "понатиниб":    "ponatinib",
    "ibrutinib":    "ibrutinib",    "ибрутиниб":    "ibrutinib",
    "osimertinib":  "osimertinib",  "осимертиниб":  "osimertinib",
    "alectinib":    "alectinib",    "алектиниб":    "alectinib",
    "crizotinib":   "crizotinib",   "кризотиниб":   "crizotinib",
    "palbociclib":  "palbociclib",  "палбоциклиб":  "palbociclib",
    "ribociclib":   "ribociclib",   "рибоциклиб":   "ribociclib",
    "abemaciclib":  "abemaciclib",  "абемациклиб":  "abemaciclib",
    "everolimus":   "everolimus",   "эверолимус":   "everolimus",
    "temsirolimus": "temsirolimus", "темсиролимус": "temsirolimus",
}


def _resolve_inn_grls(drug_name: str) -> Optional[str]:
    """
    Поиск ИНН через GRLS (Государственный реестр лекарственных средств РФ).
    Используется для дженериков, когда введено торговое название (напр. «Амлодипин-Тева»).

    API GRLS: https://grls.rosminzdrav.ru/api/v1/
    Возвращает ИНН или None если не найдено.
    """
    try:
        url = "https://grls.rosminzdrav.ru/api/v1/medicines"
        params = {"name": drug_name, "pageSize": 5}
        resp = requests.get(url, params=params, timeout=5)
        resp.raise_for_status()
        data = resp.json()

        items = data.get("data") or data.get("items") or data.get("results") or []
        if items:
            # Берём ИНН из первого результата
            first = items[0]
            inn = (
                first.get("inn")
                or first.get("mnn")
                or first.get("innLatinName")
                or first.get("mnnLatinName")
            )
            if inn and inn.strip():
                return inn.strip().lower()
    except Exception:
        pass
    return None


def _resolve_inn_rxnorm(drug_name: str) -> Optional[str]:
    """
    Поиск ИНН через RxNorm (NLM USA) — международная база.
    Возвращает ИНН или None.
    """
    try:
        url = "https://rxnav.nlm.nih.gov/REST/rxcui.json"
        resp = requests.get(url, params={"name": drug_name}, timeout=5)
        resp.raise_for_status()
        rxcui = resp.json().get("idGroup", {}).get("rxnormId", [None])[0]
        if rxcui:
            # Получаем INNs (ingredient)
            props_url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/property.json"
            props_resp = requests.get(props_url, params={"propName": "GENERIC_RXCUI"}, timeout=5)
            props_resp.raise_for_status()
            # Возвращаем просто нормализованное имя из RxNorm
            name_url = f"https://rxnav.nlm.nih.gov/REST/rxcui/{rxcui}/properties.json"
            name_resp = requests.get(name_url, timeout=5)
            name_resp.raise_for_status()
            props = name_resp.json().get("properties", {})
            name = props.get("name")
            if name:
                return name.lower().strip()
    except Exception:
        pass
    return None


def normalize_inn(drug_name: str, use_external: bool = True) -> str:
    """
    Нормализует введённое название к стандартному ИНН.

    Порядок разрешения:
      1. Локальный словарь (мгновенно)
      2. GRLS — для российских дженериков (например «Амлодипин-Тева»)
      3. RxNorm — международная база
      4. Исходное название как есть (fallback)

    Примеры ИНН (один ИНН = один уникальный препарат):
      amlodipine, metformin, atorvastatin, losartan, tacrolimus,
      ibuprofen, azithromycin, omeprazole, warfarin, levothyroxine

    Args:
        drug_name:    Введённое название (ИНН, торговое, дженерик)
        use_external: Разрешить запросы к внешним базам (GRLS, RxNorm)

    Returns:
        Стандартизованный ИНН (строка)
    """
    key = drug_name.lower().strip()

    # 1. Локальный словарь
    if key in _INN_LOCAL:
        return _INN_LOCAL[key]

    if use_external:
        # 2. GRLS
        grls_inn = _resolve_inn_grls(drug_name)
        if grls_inn:
            return grls_inn

        # 3. RxNorm
        rxnorm_inn = _resolve_inn_rxnorm(drug_name)
        if rxnorm_inn:
            return rxnorm_inn

    # 4. Fallback — возвращаем как есть
    return drug_name.strip()


# =============================================================================
# ТАБЛИЦА КВАНТИЛЕЙ t-РАСПРЕДЕЛЕНИЯ (для 90% ДИ, alpha=0.1, 1-tail 0.95)
# Используется в cv_from_ci() без зависимости от scipy
# =============================================================================
_T_TABLE_95: dict[int, float] = {
    4: 2.1318, 5: 2.0150, 6: 1.9432, 7: 1.8946, 8: 1.8595, 9: 1.8331,
    10: 1.8125, 11: 1.7959, 12: 1.7823, 13: 1.7709, 14: 1.7613, 15: 1.7531,
    16: 1.7459, 17: 1.7396, 18: 1.7341, 19: 1.7291, 20: 1.7247, 22: 1.7171,
    24: 1.7109, 26: 1.7056, 28: 1.7011, 30: 1.6973, 35: 1.6896, 40: 1.6839,
    50: 1.6759, 60: 1.6706, 80: 1.6641, 100: 1.6602, 120: 1.6577,
}
_T_INF = 1.6449  # z-квантиль (бесконечные df → нормальное распределение)


# =============================================================================
# ПРОВЕРКА ПРАВДОПОДОБНОСТИ ИЗВЛЕЧЁННЫХ PK-ПАРАМЕТРОВ
# =============================================================================

# Физиологические границы параметров: (min, max)
# Значения вне диапазона — почти наверняка артефакты regex
_PK_HARD_BOUNDS: dict[str, tuple[float, float]] = {
    "t_half":    (0.5,   200.0),      # часы: от 30 мин до ~8 суток
    "tmax":      (0.05,  36.0),       # часы: от 3 мин до 36ч (для XR форм)
    "cmax":      (0.001, 1_000_000),  # нг/мл — очень широкий диапазон
    "auc":       (0.001, 1_000_000),  # широкий диапазон
    "clearance": (0.001, 2_000),      # Л/ч или мл/мин: выше печёночного кровотока не бывает
    "vd":        (0.001, 1_000_000),  # широкий диапазон
}

# Слова-маркеры контекста «отношение/GMR» — число рядом с ними не абсолютный PK
_RATIO_RE = re.compile(
    r'\b(?:ratio|GMR|geometric\s+mean\s+ratio|test[/\s]?reference|T\s*/\s*R|'
    r'fold[- ]?change|relative\s+bioavailability|test\s+vs\.?\s+reference)\b',
    re.IGNORECASE
)


def _context(text: str, match: re.Match, before: int = 200, after: int = 200) -> str:
    """Возвращает текстовое окно вокруг совпадения regex для проверки контекста."""
    return text[max(0, match.start() - before): min(len(text), match.end() + after)]


def _valid_pk(param: str, value: float, context: str = "", text_after: str = "") -> bool:
    """
    Проверяет, является ли значение правдоподобным PK-параметром.

    Отклоняет:
      - числа, похожие на год публикации (1980–2035)
      - значения за пределами физиологических границ
      - значения ~1.0 в контексте «ratio/GMR» (это GMR, а не абсолютный PK)
      - числа 50–99, за которыми сразу идёт «%» (это «90% CI», не PK-значение)
      - нули (артефакт когда regex не нашёл реального числа)
    """
    # Ноль — почти всегда артефакт
    if value == 0.0:
        return False
    # Числа вида 2020, 2024 — чаще всего год из текста, а не PK
    if 1980 <= value <= 2035 and value == int(value):
        return False
    # Физиологические границы
    bounds = _PK_HARD_BOUNDS.get(param)
    if bounds and not (bounds[0] <= value <= bounds[1]):
        return False
    # Значение около 1.0 в контексте GMR/ratio → это отношение, а не абсолютный параметр
    if context and 0.5 <= value <= 2.5 and bool(_RATIO_RE.search(context)):
        return False
    # Число 50–99 сразу за которым идёт «%» → это процент (90% CI), а не PK
    if text_after and 50 <= value <= 99 and re.match(r'\s*%', text_after):
        return False
    return True


def _t_quantile_95(df: int) -> float:
    """Квантиль t-распределения при p=0.95 с линейной интерполяцией по таблице."""
    if df <= 0:
        return _T_INF
    if df in _T_TABLE_95:
        return _T_TABLE_95[df]
    keys = sorted(_T_TABLE_95.keys())
    if df > keys[-1]:
        return _T_INF
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= df <= hi:
            frac = (df - lo) / (hi - lo)
            return _T_TABLE_95[lo] + frac * (_T_TABLE_95[hi] - _T_TABLE_95[lo])
    return _T_INF


def cv_from_ci(
    lower: float,
    upper: float,
    n: int,
    design: str = "2x2",
    alpha: float = 0.10
) -> float:
    """
    Рассчитывает CVintra (%) из 90% ДИ отношения геометрических средних
    тест/референс — аналог CVfromCI() из R-пакета PowerTOST.

    Алгоритм для 2-периодного кроссовера с лог-трансформацией:
        df  = n - 2
        t*  = t_{1-alpha/2, df}
        s²  = ( (ln(upper) - ln(lower)) / (2 * t*) )²
        CV  = sqrt(exp(s²) - 1) × 100 %

    Args:
        lower:  Нижняя граница 90% ДИ (как отношение, напр. 0.85)
        upper:  Верхняя граница 90% ДИ (как отношение, напр. 1.18)
        n:      Суммарное число участников исследования
        design: Дизайн ("2x2" — стандартный 2-периодный кроссовер)
        alpha:  Уровень значимости (0.10 для 90% ДИ)

    Returns:
        CVintra (%) — округлён до 2 знаков

    Пример:
        cv_from_ci(0.85, 1.18, n=24)  →  ~22.5%
        cv_from_ci(0.80, 1.25, n=20)  →  ~32.1%
    """
    if lower <= 0 or upper <= 0 or lower >= upper:
        raise ValueError(f"Некорректные границы ДИ: lower={lower}, upper={upper}")
    if n < 4:
        raise ValueError(f"Слишком мало участников: n={n}")

    df = n - 2
    t_star = _t_quantile_95(df)
    s_squared = ((math.log(upper) - math.log(lower)) / (2 * t_star)) ** 2
    cv = math.sqrt(math.exp(s_squared) - 1) * 100
    return round(cv, 2)


# База данных типичных CVintra для классов препаратов (%)
TYPICAL_CV_DATABASE = {
    # Антигипертензивные
    "amlodipine": 15.0,  # низкая вариабельность
    "nifedipine": 25.0,
    "valsartan": 28.0,
    "losartan": 30.0,
    "telmisartan": 35.0,

    # Антикоагулянты
    "warfarin": 20.0,
    "rivaroxaban": 35.0,

    # Иммуносупрессанты
    "tacrolimus": 45.0,  # высокая вариабельность
    "cyclosporine": 25.0,

    # Антибиотики
    "azithromycin": 22.0,
    "ciprofloxacin": 18.0,

    # По умолчанию для неизвестных препаратов
    "default": 25.0
}


def determine_study_design(cv_intra: Optional[float] = None,
                          t_half: Optional[float] = None,
                          drug_name: Optional[str] = None) -> Tuple[str, int, str]:
    """
    Определяет дизайн исследования биоэквивалентности на основе CVintra и T½.

    Возвращает: (дизайн, рекомендуемое N, обоснование)
    """
    # Параллельный дизайн только если период отмывки (5×T½) > 21 дней
    if t_half:
        washout_days = math.ceil(5 * t_half / 24)
        if washout_days > 21:
            return ("Параллельный", 150, f"Период отмывки {washout_days} сут > 21 сут (T½={t_half}h)")

    # Если CVintra неизвестен, пробуем найти типичное значение
    if cv_intra is None and drug_name:
        drug_lower = drug_name.lower()
        cv_intra = TYPICAL_CV_DATABASE.get(drug_lower, TYPICAL_CV_DATABASE["default"])
        reasoning_suffix = f" (типичное значение для {drug_name})"
    else:
        reasoning_suffix = ""

    # Если всё равно неизвестен - берём умеренное значение
    if cv_intra is None:
        cv_intra = 25.0
        reasoning_suffix = " (предполагаемое значение)"

    # Определяем дизайн по CVintra
    if cv_intra <= 30:
        return ("2×2 Cross-over", 26, f"CVintra={cv_intra}% ≤ 30% (стандартная вариабельность){reasoning_suffix}")
    elif cv_intra <= 50:
        return ("3-way Replicate", 39, f"CVintra={cv_intra}% (30-50%, средняя вариабельность){reasoning_suffix}")
    else:
        return ("4-way Replicate (RSABE)", 54, f"CVintra={cv_intra}% > 50% (высокая вариабельность){reasoning_suffix}")


class PKSource:
    """
    Базовый класс для всех источников фармакокинетических данных.
    Определяет единый интерфейс: search -> fetch -> extract
    """
    def __init__(self):
        """Базовая инициализация источника данных."""
        self.source_name = self.__class__.__name__

    def search(self,
               drug: str,
               dosage_form: Optional[str] = None,
               dosage: Optional[float] = None,
               study_type: Optional[str] = None) -> List[str]:
        """
        Поиск записей по препарату и параметрам.
        Возвращает список идентификаторов (PMID, DrugBank ID и т.д.).
        """
        raise NotImplementedError(f"{self.source_name}.search() must be implemented")

    def fetch(self, identifier: str) -> str:
        """
        Получение полного текста/данных по идентификатору.
        Возвращает сырые данные (XML, JSON, HTML).
        """
        raise NotImplementedError(f"{self.source_name}.fetch() must be implemented")

    def extract(self, raw_data: str, drug: str, **kwargs) -> PKRecord:
        """
        Извлечение фармакокинетических параметров из сырых данных.
        Возвращает структурированный PKRecord.
        """
        raise NotImplementedError(f"{self.source_name}.extract() must be implemented")

    def _parse_value_unit(self, text: str, pattern: str) -> tuple[Optional[float], Optional[str]]:
        """
        Вспомогательный метод для извлечения значения и единицы измерения.
        Возвращает (значение, единица).
        """
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            value = float(match.group(1))
            unit = match.group(2) if len(match.groups()) > 1 else None
            return value, unit
        return None, None


class PubMed(PKSource):
    """
    Источник данных PubMed/PubMed Central.
    API документация: https://www.ncbi.nlm.nih.gov/books/NBK25501/
    """
    def __init__(self,
                 email: str = "mikhelson.g@gmail.com",
                 api_key: Optional[str] = None,
                 base_url: str = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"):
        super().__init__()
        self.email = email
        self.api_key = api_key
        self.base_url = base_url

    def search(self,
               drug: str,
               dosage_form: Optional[str] = None,
               dosage: Optional[float] = None,
               study_type: Optional[str] = None,
               max_results: int = 5) -> List[str]:
        """
        Поиск статей в PubMed по ИНН препарата.
        Используется ИНН (INN) для точного поиска — один ИНН = один препарат.
        Возвращает список PMID.
        """
        # ИНН-специфичный запрос: MeSH + Title/Abstract + Supplementary Concept
        # MeSH-термы строго соответствуют ИНН → один препарат, без торговых синонимов
        inn_term = (
            f'("{drug}"[MeSH Terms] OR "{drug}"[Title/Abstract] '
            f'OR "{drug}"[Supplementary Concept])'
        )
        # Фильтр по типу исследования — биоэквивалентность / фармакокинетика
        pk_filter = (
            '(pharmacokinetics[MeSH Terms] OR pharmacokinetics[Title/Abstract] '
            'OR bioequivalence[Title/Abstract] OR "bioavailability"[Title/Abstract])'
        )
        query_parts = [inn_term, pk_filter]

        if dosage_form:
            query_parts.append(f"{dosage_form}[Title/Abstract]")

        if study_type:
            query_parts.append(f"{study_type}[Title/Abstract]")

        query = " AND ".join(query_parts)

        params = {
            "db": "pubmed",
            "term": query,
            "retmax": max_results,
            "retmode": "xml",
            "email": self.email
        }

        if self.api_key:
            params["api_key"] = self.api_key

        response = requests.get(self.base_url + "esearch.fcgi", params=params)
        response.raise_for_status()

        root = ET.fromstring(response.text)
        id_list = root.find("IdList")

        if id_list is not None:
            pmids = [id_elem.text for id_elem in id_list.findall("Id")]
            return pmids
        return []

    def fetch(self, identifier: str) -> str:
        """
        Получение полного текста статьи из PubMed Central.
        identifier может быть PMID или PMCID.
        """
        # Если это PMID, конвертируем в PMCID
        if not identifier.startswith("PMC"):
            pmc_id = self.get_pmc_id(identifier)
            if pmc_id:
                identifier = pmc_id
            else:
                # Если нет полного текста, получаем abstract
                return self._fetch_abstract(identifier)

        params = {
            "db": "pmc",
            "id": identifier,
            "retmode": "xml",
            "email": self.email
        }

        response = requests.get(self.base_url + "efetch.fcgi", params=params)
        response.raise_for_status()

        return response.text

    def _fetch_abstract(self, pmid: str) -> str:
        """Получение аннотации статьи, если полный текст недоступен."""
        params = {
            "db": "pubmed",
            "id": pmid,
            "retmode": "xml",
            "email": self.email
        }

        response = requests.get(self.base_url + "efetch.fcgi", params=params)
        response.raise_for_status()
        return response.text

    def extract(self, xml_text: str, drug: str, **kwargs) -> PKRecord:
        """
        Извлечение фармакокинетических параметров из XML статьи.
        Возвращает PKRecord со всеми найденными параметрами.
        """
        root = ET.fromstring(xml_text)

        # Извлекаем текст из параграфов (включая вложенные элементы!)
        paragraphs = []
        for p in root.findall(".//p"):
            # itertext() извлекает весь текст, включая вложенные теги
            paragraph_text = "".join(p.itertext())
            if paragraph_text.strip():
                paragraphs.append(paragraph_text)

        text = "\n".join(paragraphs)

        # Если параграфов нет, пробуем извлечь abstract
        if not text:
            for abstract in root.findall(".//AbstractText"):
                abstract_text = "".join(abstract.itertext())
                if abstract_text.strip():
                    paragraphs.append(abstract_text)
            text = "\n".join(paragraphs)

        # Извлекаем PMID для study_id
        pmid = None
        pmid_elem = root.find(".//PMID")
        if pmid_elem is not None:
            pmid = pmid_elem.text

        # Извлекаем название статьи
        title = None
        title_elem = root.find(".//ArticleTitle")
        if title_elem is not None:
            # Используем itertext() чтобы получить весь текст, включая вложенные теги
            title = "".join(title_elem.itertext()).strip()

        # DEBUG: показываем что извлекли
        if kwargs.get("debug", False):
            print(f"\n[DEBUG] Title: {title}")
            print(f"[DEBUG] Extracted text length: {len(text)}")
            print(f"[DEBUG] First 500 chars:\n{text[:500]}...\n")

        # Создаём PKRecord
        record = PKRecord(
            source=self.source_name,
            drug=drug,
            study_id=pmid,
            title=title
        )

        # Извлекаем параметры с помощью regex + проверка правдоподобности
        record.rejected_params = []

        # Cmax
        cmax_match = re.search(r'Cmax[^0-9]*(\d+\.?\d*)\s*(ng/mL|mg/L|µg/mL|mcg/mL)?', text, re.IGNORECASE)
        if cmax_match:
            val = float(cmax_match.group(1))
            after = text[cmax_match.end(1):cmax_match.end(1)+5]
            if _valid_pk("cmax", val, _context(text, cmax_match), after):
                record.cmax = val
                record.cmax_unit = cmax_match.group(2) if cmax_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"Cmax={val}")

        # Tmax
        tmax_match = re.search(r'Tmax[^0-9]*(\d+\.?\d*)\s*(h|hour|hours|min|minutes)?', text, re.IGNORECASE)
        if tmax_match:
            val = float(tmax_match.group(1))
            after = text[tmax_match.end(1):tmax_match.end(1)+5]
            if _valid_pk("tmax", val, _context(text, tmax_match), after):
                record.tmax = val
                record.tmax_unit = tmax_match.group(2) if tmax_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"Tmax={val}")

        # AUC
        auc_match = re.search(r'AUC[^0-9]*(\d+\.?\d*)\s*(ng\*h/mL|mg\*h/L|µg\*h/mL|ng\.h/mL)?', text, re.IGNORECASE)
        if auc_match:
            val = float(auc_match.group(1))
            after = text[auc_match.end(1):auc_match.end(1)+5]
            if _valid_pk("auc", val, _context(text, auc_match), after):
                record.auc = val
                record.auc_unit = auc_match.group(2) if auc_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"AUC={val}")

        # Half-life
        half_life_match = re.search(r'(?:half[- ]?life|t½|t1/2)[^0-9]*(\d+\.?\d*)\s*(h|hour|hours)?', text, re.IGNORECASE)
        if half_life_match:
            val = float(half_life_match.group(1))
            after = text[half_life_match.end(1):half_life_match.end(1)+5]
            if _valid_pk("t_half", val, _context(text, half_life_match), after):
                record.t_half = val
                record.t_half_unit = half_life_match.group(2) if half_life_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"T½={val}h")

        # Clearance
        cl_match = re.search(r'(?:clearance|CL)[^0-9]*(\d+\.?\d*)\s*(L/h|mL/min|mL/h)?', text, re.IGNORECASE)
        if cl_match:
            val = float(cl_match.group(1))
            after = text[cl_match.end(1):cl_match.end(1)+5]
            if _valid_pk("clearance", val, _context(text, cl_match), after):
                record.clearance = val
                record.clearance_unit = cl_match.group(2) if cl_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"CL={val}")

        # Volume of distribution
        vd_match = re.search(r'(?:volume of distribution|Vd)[^0-9]*(\d+\.?\d*)\s*(L|mL)?', text, re.IGNORECASE)
        if vd_match:
            val = float(vd_match.group(1))
            after = text[vd_match.end(1):vd_match.end(1)+5]
            if _valid_pk("vd", val, _context(text, vd_match), after):
                record.volume_distribution = val
                record.vd_unit = vd_match.group(2) if vd_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"Vd={val}")

        # Количество участников (нужно до расчёта CVintra из ДИ)
        n_match = re.search(r'(\d+)\s*(?:subjects|patients|participants)', text, re.IGNORECASE)
        if n_match:
            record.n_subjects = int(n_match.group(1))

        # === CVintra extraction (ЕАЭС Решение №85: использовать наибольший из AUC и Cmax) ===

        # ШАГ 1a: CVintra раздельно по AUC
        auc_cv_patterns = [
            r'(?:AUC)[^\n]{0,80}(?:CV|coefficient of variation|variability)[^0-9]*(\d+\.?\d*)\s*%',
            r'(?:CV|coefficient of variation|variability)[^\n]{0,80}(?:AUC)[^0-9]*(\d+\.?\d*)\s*%',
        ]
        for pattern in auc_cv_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if 3.0 <= val <= 100.0:
                    record.cv_intra_auc = val
                    break

        # ШАГ 1b: CVintra раздельно по Cmax
        cmax_cv_patterns = [
            r'(?:C[- ]?max)[^\n]{0,80}(?:CV|coefficient of variation|variability)[^0-9]*(\d+\.?\d*)\s*%',
            r'(?:CV|coefficient of variation|variability)[^\n]{0,80}(?:C[- ]?max)[^0-9]*(\d+\.?\d*)\s*%',
        ]
        for pattern in cmax_cv_patterns:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if 3.0 <= val <= 100.0:
                    record.cv_intra_cmax = val
                    break

        # Выбираем наибольший (ЕАЭС: CVintra = max(AUC CV, Cmax CV))
        if record.cv_intra_auc is not None and record.cv_intra_cmax is not None:
            record.cv_intra = max(record.cv_intra_auc, record.cv_intra_cmax)
            record.cv_intra_source = "extracted"
        elif record.cv_intra_auc is not None:
            record.cv_intra = record.cv_intra_auc
            record.cv_intra_source = "extracted"
        elif record.cv_intra_cmax is not None:
            record.cv_intra = record.cv_intra_cmax
            record.cv_intra_source = "extracted"

        # ШАГ 2: Общие паттерны CVintra (если раздельно не найдено)
        if record.cv_intra is None:
            cv_patterns = [
                r'(?:intra[- ]?subject(?:[\s\-]variability)?|CVintra|CV_intra|within[- ]?subject(?:[\s\-]variability)?|intraindividual variability)[^0-9]*(\d+\.?\d*)%?',
                r'(?:CV|coefficient of variation)\s*(?:intra)?[^0-9]*(\d+\.?\d*)\s*%',
                r'variability[^0-9]*(\d+\.?\d*)\s*%',
            ]
            for pattern in cv_patterns:
                cv_match = re.search(pattern, text, re.IGNORECASE)
                if cv_match:
                    record.cv_intra = float(cv_match.group(1))
                    record.cv_intra_source = "extracted"
                    break

        # ШАГ 3: Расчёт из 90% ДИ если CVintra не найден (метод CVfromCI, аналог PowerTOST)
        if record.cv_intra is None:
            ci_patterns = [
                # "90% CI [0.85, 1.18]" / "90% CI: 0.85-1.18" / "90% CI (0.85; 1.18)"
                r'90\s*%\s*(?:CI|confidence interval)[^\d]*(\d+\.?\d*)\s*[-–,;]\s*(\d+\.?\d*)',
                # "CI (90%): 0.85 to 1.18"
                r'CI\s*\(90\s*%\)[^\d]*(\d+\.?\d*)\s*(?:to|[-–])\s*(\d+\.?\d*)',
                # "geometric mean ratio ... 90% ... 0.92 ... 1.12"
                r'geometric mean ratio[^\d]*(\d+\.?\d*)[^\d]+(\d+\.?\d*)[^\d]+90',
                # "GMR.*90%.*0.85.*1.18" — гибкий паттерн
                r'GMR[^\d]*(\d+\.?\d*)[^\d]+(\d+\.?\d*)',
            ]
            for pattern in ci_patterns:
                ci_match = re.search(pattern, text, re.IGNORECASE)
                if ci_match:
                    raw_lo = float(ci_match.group(1))
                    raw_hi = float(ci_match.group(2))
                    # Конвертируем проценты → отношение (85.0 → 0.850)
                    if raw_lo > 2:
                        raw_lo /= 100.0
                        raw_hi /= 100.0
                    # Санитарная проверка: допустимые границы ДИ для биоэквивалентности
                    if 0.5 < raw_lo < 1.0 < raw_hi < 2.0:
                        record.ci_lower = raw_lo
                        record.ci_upper = raw_hi
                        if record.n_subjects and record.n_subjects >= 4:
                            try:
                                record.cv_intra = cv_from_ci(raw_lo, raw_hi, record.n_subjects)
                                record.cv_intra_source = "calculated_from_ci"
                            except ValueError:
                                pass
                        break

        return record

    def get_pmc_id(self, pmid: str) -> Optional[str]:
        """
        Конвертация PMID в PMCID для получения полного текста.
        """
        params = {
            "dbfrom": "pubmed",
            "db": "pmc",
            "id": pmid,
            "retmode": "xml",
            "email": self.email
        }

        response = requests.get(self.base_url + "elink.fcgi", params=params)
        response.raise_for_status()

        root = ET.fromstring(response.text)

        for link in root.findall(".//Link"):
            pmcid = link.find("Id")
            if pmcid is not None:
                return pmcid.text

        return None

class OpenFDA(PKSource):
    """
    Источник данных OpenFDA (FDA Drug Label API).
    Бесплатный API, не требует ключа: https://open.fda.gov/apis/drug/label/
    """
    BASE_URL = "https://api.fda.gov/drug/label.json"

    def __init__(self):
        super().__init__()
        self._cache: dict = {}

    def search(
        self,
        drug: str,
        dosage_form: Optional[str] = None,
        dosage: Optional[float] = None,
        study_type: Optional[str] = None,
        max_results: int = 3
    ) -> List[str]:
        """Поиск инструкций по ИНН через OpenFDA. Возвращает список идентификаторов."""
        # OpenFDA индексирует только латинские generic names — кириллица даст 400 Bad Request
        if not drug.isascii():
            print(f"⚠️  OpenFDA: пропуск — имя «{drug}» содержит не-ASCII символы (FDA принимает только латиницу)")
            return []
        search_query = f'openfda.generic_name:"{drug.lower()}"'
        params = {"search": search_query, "limit": max_results}

        resp = requests.get(self.BASE_URL, params=params, timeout=10)
        if resp.status_code == 404:
            return []
        resp.raise_for_status()

        results = resp.json().get("results", [])
        ids = []
        for i, item in enumerate(results):
            app_nums = item.get("openfda", {}).get("application_number", [])
            item_id = app_nums[0] if app_nums else f"fda_{drug}_{i}"
            self._cache[item_id] = item
            ids.append(item_id)
        return ids

    def fetch(self, identifier: str) -> str:
        """Возвращает данные FDA label из кеша."""
        if identifier in self._cache:
            return json.dumps(self._cache[identifier])
        raise KeyError(f"OpenFDA: identifier {identifier} not found in cache")

    def extract(self, raw_data: str, drug: str, **kwargs) -> PKRecord:
        """Извлекает PK параметры из FDA label JSON."""
        data = json.loads(raw_data)
        openfda = data.get("openfda", {})

        record = PKRecord(
            source=self.source_name,
            drug=drug,
            study_id=next(iter(openfda.get("application_number", [])), None),
            title=(next(iter(openfda.get("brand_name", [])), drug) + " [FDA Label]"),
        )

        # Объединяем PK-релевантные разделы
        pk_sections: List[str] = []
        for section in ["clinical_pharmacology", "pharmacokinetics",
                         "clinical_pharmacology_table"]:
            if section in data:
                pk_sections.extend(data[section])
        text = " ".join(pk_sections)

        if not text.strip():
            return record

        record.rejected_params = []

        # Cmax
        cmax_match = re.search(r'Cmax[^0-9]*(\d+\.?\d*)\s*(ng/mL|mg/L|µg/mL|mcg/mL)?', text, re.IGNORECASE)
        if cmax_match:
            val = float(cmax_match.group(1))
            after = text[cmax_match.end(1):cmax_match.end(1)+5]
            if _valid_pk("cmax", val, _context(text, cmax_match), after):
                record.cmax = val
                record.cmax_unit = cmax_match.group(2) if cmax_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"Cmax={val}")

        # Tmax
        tmax_match = re.search(r'Tmax[^0-9]*(\d+\.?\d*)\s*(h|hour|hours|min|minutes)?', text, re.IGNORECASE)
        if tmax_match:
            val = float(tmax_match.group(1))
            after = text[tmax_match.end(1):tmax_match.end(1)+5]
            if _valid_pk("tmax", val, _context(text, tmax_match), after):
                record.tmax = val
                record.tmax_unit = tmax_match.group(2) if tmax_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"Tmax={val}")

        # AUC
        auc_match = re.search(r'AUC[^0-9]*(\d+\.?\d*)\s*(ng\*h/mL|mg\*h/L|µg\*h/mL|ng\.h/mL)?', text, re.IGNORECASE)
        if auc_match:
            val = float(auc_match.group(1))
            after = text[auc_match.end(1):auc_match.end(1)+5]
            if _valid_pk("auc", val, _context(text, auc_match), after):
                record.auc = val
                record.auc_unit = auc_match.group(2) if auc_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"AUC={val}")

        # Half-life
        hl_match = re.search(r'(?:half[- ]?life|t½|t1/2)[^0-9]*(\d+\.?\d*)\s*(h|hour|hours)?', text, re.IGNORECASE)
        if hl_match:
            val = float(hl_match.group(1))
            after = text[hl_match.end(1):hl_match.end(1)+5]
            if _valid_pk("t_half", val, _context(text, hl_match), after):
                record.t_half = val
                record.t_half_unit = hl_match.group(2) if hl_match.lastindex >= 2 else None
            else:
                record.rejected_params.append(f"T½={val}h")

        # N subjects
        n_match = re.search(r'(\d+)\s*(?:subjects|patients|participants)', text, re.IGNORECASE)
        if n_match:
            record.n_subjects = int(n_match.group(1))

        # CVintra (FDA labels редко содержат, но проверяем)
        for pattern in [
            r'(?:intra[- ]?subject|CVintra|CV_intra|within[- ]?subject)[^0-9]*(\d+\.?\d*)\s*%',
            r'(?:CV|coefficient of variation)\s*(?:intra)?[^0-9]*(\d+\.?\d*)\s*%',
        ]:
            m = re.search(pattern, text, re.IGNORECASE)
            if m:
                val = float(m.group(1))
                if 3.0 <= val <= 100.0:
                    record.cv_intra = val
                    record.cv_intra_source = "extracted"
                    break

        return record


def merge_pk_records(records: List[PKRecord], drug: str) -> PKRecord:
    """
    Объединяет несколько PKRecord в одну «лучшую» запись, дополняя
    отсутствующие параметры из других источников.

    Стратегия приоритетов:
      CVintra:  extracted > calculated_from_ci > TYPICAL_CV_DATABASE
      T½, Cmax, AUC, Tmax: OpenFDA (FDA label) > PubMed
      CL, Vd: первое найденное ненулевое значение
      n_subjects: максимальное (самое репрезентативное исследование)

    Args:
        records: список PKRecord из разных статей
        drug:    ИНН действующего вещества

    Returns:
        Один PKRecord с заполненными полями из лучших источников.
        Поле study_id содержит список всех PMID через запятую.
        Поле title содержит количество объединённых источников.
    """
    if not records:
        return PKRecord(source="merged", drug=drug)

    merged = PKRecord(
        source="merged",
        drug=drug,
    )

    # --- n_subjects: берём максимальное ---
    n_vals = [r.n_subjects for r in records if r.n_subjects]
    if n_vals:
        merged.n_subjects = max(n_vals)

    # --- Простые параметры ---
    # Для абсолютных PK (T½, Cmax, AUC, Tmax): FDA label более авторитетен,
    # так как данные взяты из оригинального NDA/ANDA.
    # CL и Vd: нет явного предпочтения источника.
    fda_first   = [r for r in records if r.source == "OpenFDA"] + \
                  [r for r in records if r.source != "OpenFDA"]
    order_map = {
        "cmax":               fda_first,
        "tmax":               fda_first,
        "auc":                fda_first,
        "t_half":             fda_first,
        "clearance":          records,
        "volume_distribution": records,
    }
    for field, unit_field in [
        ("cmax",               "cmax_unit"),
        ("tmax",               "tmax_unit"),
        ("auc",                "auc_unit"),
        ("t_half",             "t_half_unit"),
        ("clearance",          "clearance_unit"),
        ("volume_distribution","vd_unit"),
    ]:
        for r in order_map[field]:
            val = getattr(r, field)
            if val is not None:
                setattr(merged, field, val)
                setattr(merged, unit_field, getattr(r, unit_field))
                break

    # --- CVintra: приоритет по источнику ---
    # Собираем все найденные CVintra по приоритету
    _prio = {"extracted": 0, "calculated_from_ci": 1, "database": 2}
    best_cv_record = None
    for r in records:
        if r.cv_intra is None:
            continue
        if best_cv_record is None:
            best_cv_record = r
        else:
            cur_prio  = _prio.get(r.cv_intra_source or "database", 2)
            best_prio = _prio.get(best_cv_record.cv_intra_source or "database", 2)
            if cur_prio < best_prio:
                best_cv_record = r

    if best_cv_record:
        merged.cv_intra        = best_cv_record.cv_intra
        merged.cv_intra_source = best_cv_record.cv_intra_source
        merged.ci_lower        = best_cv_record.ci_lower
        merged.ci_upper        = best_cv_record.ci_upper
    else:
        # Фоллбэк: берём из базы типичных значений
        db_val = TYPICAL_CV_DATABASE.get(drug.lower(), TYPICAL_CV_DATABASE["default"])
        merged.cv_intra        = db_val
        merged.cv_intra_source = "database"

    # --- cv_intra_auc / cv_intra_cmax: лучшее из доступных ---
    for field in ("cv_intra_auc", "cv_intra_cmax"):
        for r in records:
            val = getattr(r, field)
            if val is not None:
                setattr(merged, field, val)
                break
    # Пересчитываем итоговый CVintra по правилу ЕАЭС (max из AUC и Cmax)
    if merged.cv_intra_auc is not None and merged.cv_intra_cmax is not None:
        recalc = max(merged.cv_intra_auc, merged.cv_intra_cmax)
        if merged.cv_intra_source == "extracted":
            merged.cv_intra = recalc
    elif merged.cv_intra_auc is not None and merged.cv_intra_source == "extracted":
        merged.cv_intra = merged.cv_intra_auc
    elif merged.cv_intra_cmax is not None and merged.cv_intra_source == "extracted":
        merged.cv_intra = merged.cv_intra_cmax

    # --- Метаданные ---
    pmids = [r.study_id for r in records if r.study_id]
    merged.study_id = ", ".join(pmids) if pmids else None
    merged.title    = f"Объединено из {len(records)} источника(ов): {', '.join(pmids)}" if pmids else f"{len(records)} sources"

    return merged


def get_pk_data_from_all_sources(
    drug: str,
    dosage_form: Optional[str] = None,
    dosage: Optional[float] = None,
    max_pubmed: int = 10,
    max_fda: int = 3,
) -> List[PKRecord]:
    """
    Собирает фармакокинетические данные из всех доступных источников.

    Args:
        max_pubmed: максимальное количество статей из PubMed
        max_fda:    максимальное количество инструкций из OpenFDA
    """
    all_records = []

    # PubMed (всегда доступен)
    pubmed = PubMed()
    try:
        pmids = pubmed.search(drug, dosage_form=dosage_form, max_results=max_pubmed)
        print(f"\n✓ Found {len(pmids)} articles: {pmids}\n")

        for i, pmid in enumerate(pmids, 1):
            print(f"\n{'='*80}")
            print(f"[{i}/{len(pmids)}] Processing PMID {pmid}")
            print(f"{'='*80}")

            xml_data = pubmed.fetch(pmid)
            record = pubmed.extract(xml_data, drug, debug=False)

            # Показываем название статьи
            if record.title:
                print(f"📄 Title: {record.title}")

            # Показываем что нашли
            found_params = []
            if record.cmax: found_params.append(f"Cmax={record.cmax} {record.cmax_unit or ''}")
            if record.tmax: found_params.append(f"Tmax={record.tmax} {record.tmax_unit or ''}")
            if record.auc: found_params.append(f"AUC={record.auc} {record.auc_unit or ''}")
            if record.t_half: found_params.append(f"T½={record.t_half} {record.t_half_unit or ''}")
            if record.clearance: found_params.append(f"CL={record.clearance} {record.clearance_unit or ''}")
            if record.cv_intra:
                src = f" [{record.cv_intra_source}]" if record.cv_intra_source else ""
                found_params.append(f"CVintra={record.cv_intra}%{src}")
            if record.ci_lower:
                found_params.append(f"90%CI=[{record.ci_lower:.3f}; {record.ci_upper:.3f}]")

            if found_params:
                print(f"✓ Found: {', '.join(found_params)}")
            else:
                print("✗ No PK parameters found")
            if record.rejected_params:
                print(f"  ↳ Отклонено (нереалист.): {', '.join(record.rejected_params)}")

            all_records.append(record)
    except Exception as e:
        print(f"❌ PubMed error: {e}")
        import traceback
        traceback.print_exc()

    # OpenFDA (бесплатный, без ключа)
    openfda = OpenFDA()
    try:
        fda_ids = openfda.search(drug, dosage_form=dosage_form, max_results=max_fda)
        print(f"\n✓ OpenFDA: найдено {len(fda_ids)} инструкций: {fda_ids}\n")

        for i, fda_id in enumerate(fda_ids, 1):
            print(f"\n{'='*80}")
            print(f"[OpenFDA {i}/{len(fda_ids)}] {fda_id}")
            print(f"{'='*80}")

            raw = openfda.fetch(fda_id)
            record = openfda.extract(raw, drug)

            if record.title:
                print(f"📄 Title: {record.title}")

            found_params = []
            if record.cmax:   found_params.append(f"Cmax={record.cmax} {record.cmax_unit or ''}")
            if record.tmax:   found_params.append(f"Tmax={record.tmax} {record.tmax_unit or ''}")
            if record.auc:    found_params.append(f"AUC={record.auc} {record.auc_unit or ''}")
            if record.t_half: found_params.append(f"T½={record.t_half} {record.t_half_unit or ''}")
            if record.cv_intra:
                src = f" [{record.cv_intra_source}]" if record.cv_intra_source else ""
                found_params.append(f"CVintra={record.cv_intra}%{src}")

            if found_params:
                print(f"✓ Found: {', '.join(found_params)}")
            else:
                print("✗ No PK parameters found in FDA label")
            if record.rejected_params:
                print(f"  ↳ Отклонено (нереалист.): {', '.join(record.rejected_params)}")

            all_records.append(record)
    except Exception as e:
        print(f"⚠️  OpenFDA error (non-critical): {e}")

    return all_records

if __name__ == "__main__":
    get_pk_data_from_all_sources("Amlodipine", max_results=5)