import re
import requests
import xml.etree.ElementTree as ET
from typing import List, Optional, Tuple
from .pk_record import PKRecord


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
    # Если T½ очень большой (> 24 часов) -> параллельный дизайн
    if t_half and t_half > 24:
        return ("Parallel", 150, f"Пролонгированное действие (T½={t_half}h)")

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
        Поиск статей в PubMed по препарату.
        Возвращает список PMID.
        """
        # Формируем поисковый запрос
        query_parts = [f"{drug}[Title/Abstract]", "pharmacokinetics[Title/Abstract]"]

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

        # Извлекаем параметры с помощью regex (используем гибкие паттерны!)
        # Cmax - ищем любые символы между "Cmax" и числом
        cmax_match = re.search(r'Cmax[^0-9]*(\d+\.?\d*)\s*(ng/mL|mg/L|µg/mL|mcg/mL)?', text, re.IGNORECASE)
        if cmax_match:
            record.cmax = float(cmax_match.group(1))
            record.cmax_unit = cmax_match.group(2) if cmax_match.lastindex >= 2 else None

        # Tmax
        tmax_match = re.search(r'Tmax[^0-9]*(\d+\.?\d*)\s*(h|hour|hours|min|minutes)?', text, re.IGNORECASE)
        if tmax_match:
            record.tmax = float(tmax_match.group(1))
            record.tmax_unit = tmax_match.group(2) if tmax_match.lastindex >= 2 else None

        # AUC
        auc_match = re.search(r'AUC[^0-9]*(\d+\.?\d*)\s*(ng\*h/mL|mg\*h/L|µg\*h/mL|ng\.h/mL)?', text, re.IGNORECASE)
        if auc_match:
            record.auc = float(auc_match.group(1))
            record.auc_unit = auc_match.group(2) if auc_match.lastindex >= 2 else None

        # Half-life
        half_life_match = re.search(r'(?:half[- ]?life|t½|t1/2)[^0-9]*(\d+\.?\d*)\s*(h|hour|hours)?', text, re.IGNORECASE)
        if half_life_match:
            record.t_half = float(half_life_match.group(1))
            record.t_half_unit = half_life_match.group(2) if half_life_match.lastindex >= 2 else None

        # Clearance
        cl_match = re.search(r'(?:clearance|CL)[^0-9]*(\d+\.?\d*)\s*(L/h|mL/min|mL/h)?', text, re.IGNORECASE)
        if cl_match:
            record.clearance = float(cl_match.group(1))
            record.clearance_unit = cl_match.group(2) if cl_match.lastindex >= 2 else None

        # Volume of distribution
        vd_match = re.search(r'(?:volume of distribution|Vd)[^0-9]*(\d+\.?\d*)\s*(L|mL)?', text, re.IGNORECASE)
        if vd_match:
            record.volume_distribution = float(vd_match.group(1))
            record.vd_unit = vd_match.group(2) if vd_match.lastindex >= 2 else None

        # CVintra - расширенный поиск вариабельности
        cv_patterns = [
            r'(?:intra[- ]?subject variability|CVintra|within[- ]subject variability|intraindividual variability)[^0-9]*(\d+\.?\d*)%?',
            r'(?:CV|coefficient of variation)[^0-9]*(\d+\.?\d*)%',
            r'variability[^0-9]*(\d+\.?\d*)%'
        ]

        for pattern in cv_patterns:
            cv_match = re.search(pattern, text, re.IGNORECASE)
            if cv_match:
                record.cv_intra = float(cv_match.group(1))
                break  # Берём первое найденное значение

        # Количество участников
        n_match = re.search(r'(\d+)\s*(?:subjects|patients|participants)', text, re.IGNORECASE)
        if n_match:
            record.n_subjects = int(n_match.group(1))

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


class DrugBank(PKSource):
    """
    Источник данных DrugBank.
    Требует API ключ: https://www.drugbank.ca/
    """
    def __init__(self, api_key: str):
        super().__init__()
        self.api_key = api_key
        self.base_url = "https://api.drugbank.com/v1"

    def search(self,
               drug: str,
               dosage_form: Optional[str] = None,
               dosage: Optional[float] = None,
               study_type: Optional[str] = None) -> List[str]:
        """
        Поиск препарата в DrugBank.
        Возвращает список DrugBank ID.
        """
        # TODO: Реализовать поиск через DrugBank API
        # Пример: GET /drugs?q={drug}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        params = {"q": drug}

        response = requests.get(f"{self.base_url}/drugs", headers=headers, params=params)
        response.raise_for_status()

        data = response.json()
        return [item["drugbank_id"] for item in data.get("results", [])]

    def fetch(self, identifier: str) -> str:
        """
        Получение данных о препарате из DrugBank.
        """
        # TODO: Реализовать получение данных
        # Пример: GET /drugs/{drugbank_id}
        headers = {"Authorization": f"Bearer {self.api_key}"}

        response = requests.get(f"{self.base_url}/drugs/{identifier}", headers=headers)
        response.raise_for_status()

        return response.text

    def extract(self, raw_data: str, drug: str, **kwargs) -> PKRecord:
        """
        Извлечение фармакокинетических параметров из DrugBank JSON.
        """
        import json
        data = json.loads(raw_data)

        record = PKRecord(
            source=self.source_name,
            drug=drug,
            study_id=data.get("drugbank_id")
        )

        # TODO: Парсинг специфичных для DrugBank полей
        # DrugBank предоставляет структурированные данные в JSON

        return record


class CertaraSimcyp(PKSource):
    """
    Источник данных Certara Simcyp Simulator.
    Работа через локальную базу данных или API симулятора.
    """
    def __init__(self, db_path: Optional[str] = None):
        super().__init__()
        self.db_path = db_path

    def search(self,
               drug: str,
               dosage_form: Optional[str] = None,
               dosage: Optional[float] = None,
               study_type: Optional[str] = None) -> List[str]:
        """
        Поиск препарата в базе Simcyp.
        """
        # TODO: Реализовать поиск в локальной базе Simcyp
        # Обычно это SQLite или CSV файлы
        raise NotImplementedError("Simcyp integration requires database access")

    def fetch(self, identifier: str) -> str:
        """
        Получение данных из Simcyp базы.
        """
        # TODO: Реализовать чтение из базы
        raise NotImplementedError("Simcyp integration requires database access")

    def extract(self, raw_data: str, drug: str, **kwargs) -> PKRecord:
        """
        Извлечение параметров из Simcyp данных.
        """
        # TODO: Парсинг Simcyp форматов
        record = PKRecord(
            source=self.source_name,
            drug=drug
        )
        return record


class GRLS(PKSource):
    """
    Источник данных GRLS (Государственный реестр лекарственных средств РФ).
    """
    def __init__(self):
        super().__init__()
        self.base_url = "https://grls.rosminzdrav.ru"

    def search(self,
               drug: str,
               dosage_form: Optional[str] = None,
               dosage: Optional[float] = None,
               study_type: Optional[str] = None) -> List[str]:
        """
        Поиск препарата в GRLS.
        Возвращает список регистрационных номеров.
        """
        # TODO: Реализовать парсинг GRLS сайта
        # GRLS не имеет официального API, требуется web scraping
        raise NotImplementedError("GRLS integration requires web scraping")

    def fetch(self, identifier: str) -> str:
        """
        Получение инструкции и данных о препарате из GRLS.
        """
        # TODO: Реализовать скрейпинг страницы препарата
        raise NotImplementedError("GRLS integration requires web scraping")

    def extract(self, raw_data: str, drug: str, **kwargs) -> PKRecord:
        """
        Извлечение фармакокинетических параметров из инструкции GRLS.
        """
        record = PKRecord(
            source=self.source_name,
            drug=drug
        )

        # TODO: Парсинг раздела "Фармакокинетика" из HTML
        # Обычно это неструктурированный текст, требуется NLP

        return record


# Пример использования всех источников
def get_pk_data_from_all_sources(
    drug: str,
    dosage_form: Optional[str] = None,
    dosage: Optional[float] = None,
    max_results: int = 3
) -> List[PKRecord]:
    """
    Собирает фармакокинетические данные из всех доступных источников.
    """
    all_records = []

    # PubMed (всегда доступен)
    pubmed = PubMed()
    try:
        pmids = pubmed.search(drug, dosage_form=dosage_form, max_results=max_results)
        print(f"\n✓ Found {len(pmids)} articles: {pmids}\n")

        for i, pmid in enumerate(pmids, 1):
            if pmid != '32109991':
                continue
            print(f"\n{'='*80}")
            print(f"[{i}/{len(pmids)}] Processing PMID {pmid}")
            print(f"{'='*80}")

            xml_data = pubmed.fetch(pmid)
            record = pubmed.extract(xml_data, drug, debug=True)

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
            if record.cv_intra: found_params.append(f"CVintra={record.cv_intra}%")

            if found_params:
                print(f"✓ Found: {', '.join(found_params)}")
            else:
                print("✗ No PK parameters found")

            all_records.append(record)
    except Exception as e:
        print(f"❌ PubMed error: {e}")
        import traceback
        traceback.print_exc()

    # DrugBank (требует API ключ)
    # drugbank = DrugBank(api_key="YOUR_API_KEY")
    # ...

    # TODO: Добавить остальные источники по мере их реализации

    return all_records

if __name__ == "__main__":
    get_pk_data_from_all_sources("Amlodipine", max_results=5)