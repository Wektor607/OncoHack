#!/usr/bin/env python3
"""
FastAPI backend for OncoHack — bioequivalence study design tool.

Endpoints:
    POST /api/analyze          → start background job, returns job_id
    GET  /api/stream/{job_id}  → SSE: real-time progress log
    GET  /api/status/{job_id}  → job status + elapsed time
    GET  /api/preview/{job_id} → HTML preview of the generated .docx
    GET  /api/download/{job_id}→ download the generated .docx
    GET  /api/metrics/{job_id} → quality metrics JSON
"""

import asyncio
import json
import statistics
import time
import uuid
from argparse import Namespace
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()  # читает .env локально; в Docker env_file в compose делает то же самое
from typing import Optional

import mammoth
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse
from pydantic import BaseModel

from extraction.pk_source import get_pk_data_from_all_sources, normalize_inn, merge_pk_records
from extraction.sample_size import calculate_washout_period
from models.design_recommender import DesignRecommender, save_recommendation_to_json
from models.llm_config import get_llm_provider, get_translate_provider
from generate_synopsis import fill_template

# ── App setup ────────────────────────────────────────────────────────────────

app = FastAPI(title="BE Study Design API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

OUTPUTS_DIR = Path("outputs")
TEMPLATE_PATH = Path("synopsis_template.docx")

# In-memory job store (keyed by job_id)
jobs: dict[str, dict] = {}

# ── Request model ─────────────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    drug: str
    form: Optional[str] = None
    strength: Optional[float] = None
    strength_unit: str = "mg"
    dosing: str = "однократный"
    dose_number: Optional[float] = None
    dose_unit: str = "mg"
    isv: str = "auto"
    isv_cv: Optional[float] = None
    rsabe: str = "auto"
    design: str = "auto"
    design_notes: Optional[str] = None
    fed_state: str = "натощак"
    meal_type: Optional[str] = None
    study_type: str = "model_selected"
    sex: str = "any"
    age_min: Optional[int] = None
    age_max: Optional[int] = None
    constraints: Optional[list] = None
    max_pubmed: int = 10
    max_fda: int = 10

# ── Helpers ───────────────────────────────────────────────────────────────────

def _send(job_id: str, msg_type: str, **kwargs):
    """Thread-safe append of a progress event to the job's message list."""
    jobs[job_id]["messages"].append({"type": msg_type, "ts": time.time(), **kwargs})

# ── Main analysis pipeline (runs in a thread via asyncio.to_thread) ───────────

def _run_analysis(job_id: str, params: dict):
    jobs[job_id]["status"] = "running"
    try:
        # ── 1. Normalize INN ──────────────────────────────────────────────────
        _send(job_id, "step", step="init", message="Нормализация ИНН препарата...")
        drug_input = params["drug"]
        inn = normalize_inn(drug_input)
        if inn.lower() != drug_input.lower():
            _send(job_id, "log", message=f"ИНН нормализован: «{drug_input}» → «{inn}»")

        # Если после нормализации осталась кириллица — LLM переводит в English INN
        if not inn.isascii():
            _send(job_id, "log", message=f"Кириллическое название — запрашиваем перевод у LLM...")
            try:
                _llm = get_llm_provider()
                _translated = _llm.generate(
                    f"Переведи название препарата «{drug_input}» в его английский МНН (INN, International Nonproprietary Name).\n"
                    f"Ответь ТОЛЬКО английским МНН, ничего больше. Только одно слово или короткая фраза на латинице.",
                    system_prompt="Ты фармаколог-эксперт. Отвечай только английским МНН препарата, без пояснений."
                ).strip().lower()
                if _translated and _translated.isascii() and len(_translated) > 2:
                    _send(job_id, "log", message=f"LLM перевёл: «{drug_input}» → «{_translated}»")
                    inn = _translated
                else:
                    _send(job_id, "log", message=f"LLM не смог перевести, используем исходное название")
            except Exception as _e:
                _send(job_id, "log", message=f"Перевод через LLM недоступен: {_e}")

        drug = inn

        # ── 2. Extract PK data ────────────────────────────────────────────────
        _send(job_id, "step", step="extraction",
              message=f"Поиск фармакокинетических данных для «{drug}»...")

        records = get_pk_data_from_all_sources(
            drug=drug,
            dosage_form=params.get("form"),
            max_pubmed=params.get("max_pubmed", 10),
            max_fda=params.get("max_fda", 3),
        )

        if not records:
            _send(job_id, "error",
                  message="Данные не найдены. Попробуйте другой препарат или увеличьте количество статей.")
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"] = "No data found"
            return

        has_cmax   = sum(1 for r in records if r.cmax)
        has_auc    = sum(1 for r in records if r.auc)
        has_t_half = sum(1 for r in records if r.t_half)
        has_cv     = sum(1 for r in records if r.cv_intra)

        _send(job_id, "log",
              message=f"Найдено источников: {len(records)} | Cmax: {has_cmax} | AUC: {has_auc} | T½: {has_t_half} | CVintra: {has_cv}")

        merged = merge_pk_records(records, drug)

        if merged.t_half:
            washout = calculate_washout_period(merged.t_half)
            _send(job_id, "log",
                  message=f"T½ = {merged.t_half} {merged.t_half_unit or 'h'} → период отмывки: "
                          f"{washout['washout_rec_h']}ч ({washout['washout_rec_days']} сут)")

        if merged.cv_intra:
            src = merged.cv_intra_source or "extracted"
            _send(job_id, "log", message=f"CVintra = {merged.cv_intra}% [{src}]")

        # ── 3. LLM recommendation ─────────────────────────────────────────────
        _send(job_id, "step", step="llm",
              message="LLM-анализ данных и выбор дизайна исследования...")

        llm = get_llm_provider()
        translate_llm = get_translate_provider()
        recommender = DesignRecommender(llm, translate_provider=translate_llm)
        records_for_llm = [merged] + records

        recommendation = recommender.recommend_design(
            drug=drug,
            records=records_for_llm,
            dosage_form=params.get("form"),
        )

        _send(job_id, "log",
              message=f"Дизайн: {recommendation['design']} | "
                      f"Участников: {recommendation['n_subjects']} | "
                      f"CVintra: {recommendation.get('cv_intra_used')}%")
        _send(job_id, "log", message="Перевод обоснования на русский язык...")

        # ── Save JSON ─────────────────────────────────────────────────────────
        OUTPUTS_DIR.mkdir(exist_ok=True)
        json_filename = f"recommendation_{drug.lower().replace(' ', '_')}.json"
        save_recommendation_to_json(recommendation, json_filename)
        json_filepath = OUTPUTS_DIR / json_filename

        # ── 4. Generate synopsis ──────────────────────────────────────────────
        _send(job_id, "step", step="docx",
              message="Генерация синопсиса протокола (Word-документ)...")

        docx_filename = f"synopsis_{job_id}.docx"
        docx_filepath = OUTPUTS_DIR / docx_filename

        args = Namespace(
            drug=drug,
            form=params.get("form"),
            strength=params.get("strength"),
            strength_unit=params.get("strength_unit", "mg"),
            dosing=params.get("dosing", "однократный"),
            dose_number=params.get("dose_number"),
            dose_unit=params.get("dose_unit", "mg"),
            fed_state=params.get("fed_state", "натощак"),
            meal_type=params.get("meal_type"),
        )

        design_synopsis = (
            recommendation.get("design_synopsis") or recommendation.get("reasoning", "")
        )
        fill_template(args, str(json_filepath), str(docx_filepath), str(TEMPLATE_PATH), design_synopsis, records=records)

        # ── Compute quality metrics ───────────────────────────────────────────
        cv_values = [r.cv_intra for r in records if r.cv_intra]
        cv_std = round(statistics.stdev(cv_values), 2) if len(cv_values) > 1 else None

        pk_params = ["cmax", "auc", "t_half", "cv_intra", "tmax"]
        covered = sum(1 for p in pk_params if getattr(merged, p, None))

        cv_reliability_labels = {
            "extracted":          "Извлечён из статьи",
            "calculated_from_ci": "Рассчитан из 90% ДИ",
            "database":           "Из базы данных",
        }
        cv_rel = cv_reliability_labels.get(
            merged.cv_intra_source or "", "Типичное значение (assumed)"
        )

        generation_time = round(time.time() - jobs[job_id]["start_time"], 1)

        metrics = {
            "sources_count":       len(records),
            "data_coverage":       round(covered / len(pk_params) * 100),
            "cv_reliability":      cv_rel,
            "sources_consistency": cv_std,
            "generation_time":     generation_time,
            "design":              recommendation["design"],
            "n_subjects":          recommendation["n_subjects"],
            "cv_intra":            recommendation.get("cv_intra_used"),
            "t_half":              recommendation.get("t_half_used"),
        }

        jobs[job_id]["result"] = {
            "docx_filename": docx_filename,
            "metrics":       metrics,
        }
        jobs[job_id]["status"]   = "done"
        jobs[job_id]["end_time"] = time.time()

        _send(job_id, "done",
              message=f"Готово! Синопсис сгенерирован за {generation_time} сек.")

    except Exception as exc:
        import traceback
        print(traceback.format_exc())
        _send(job_id, "error", message=f"Ошибка: {exc}")
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(exc)

# ── API routes ────────────────────────────────────────────────────────────────

@app.post("/api/analyze")
async def start_analysis(request: AnalyzeRequest):
    """Start analysis job, return job_id immediately."""
    job_id = str(uuid.uuid4())
    jobs[job_id] = {
        "status":     "pending",
        "messages":   [],
        "result":     None,
        "error":      None,
        "start_time": time.time(),
        "end_time":   None,
        "params":     request.model_dump(),
    }
    asyncio.create_task(asyncio.to_thread(_run_analysis, job_id, request.model_dump()))
    return {"job_id": job_id}


@app.get("/api/stream/{job_id}")
async def stream_progress(job_id: str):
    """SSE endpoint: streams progress messages until job completes or errors."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")

    async def generate():
        sent = 0
        while True:
            job = jobs[job_id]
            while sent < len(job["messages"]):
                msg = job["messages"][sent]
                sent += 1
                yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
            if job["status"] in ("done", "error") and sent >= len(job["messages"]):
                break
            await asyncio.sleep(0.3)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/status/{job_id}")
async def get_status(job_id: str):
    """Quick status poll (used as SSE fallback)."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    return {
        "status":  job["status"],
        "error":   job.get("error"),
        "elapsed": round(time.time() - job["start_time"], 1),
    }


@app.get("/api/preview/{job_id}", response_class=HTMLResponse)
async def preview_docx(job_id: str):
    """Convert generated .docx to HTML and return it for in-browser preview."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(400, "Job not finished yet")

    docx_path = OUTPUTS_DIR / job["result"]["docx_filename"]
    if not docx_path.exists():
        raise HTTPException(404, "Document file not found")

    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(f)

    return HTMLResponse(f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: 'Times New Roman', serif;
      font-size: 12pt;
      line-height: 1.5;
      padding: 24px 40px;
      margin: 0;
      color: #111;
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      margin: 8px 0;
    }}
    td, th {{
      border: 1px solid #999;
      padding: 6px 10px;
      vertical-align: top;
    }}
    p {{ margin: 3px 0; }}
    strong {{ font-weight: bold; }}
  </style>
</head>
<body>
{result.value}
</body>
</html>""")


@app.get("/api/download/{job_id}")
async def download_docx(job_id: str):
    """Return the generated .docx file as a download."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(400, "Job not finished yet")

    docx_path = OUTPUTS_DIR / job["result"]["docx_filename"]
    drug = job["params"]["drug"]
    return FileResponse(
        docx_path,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        filename=f"synopsis_{drug}.docx",
    )


@app.get("/api/metrics/{job_id}")
async def get_metrics(job_id: str):
    """Return quality metrics for a completed job."""
    if job_id not in jobs:
        raise HTTPException(404, "Job not found")
    job = jobs[job_id]
    if job["status"] != "done":
        raise HTTPException(400, "Job not finished yet")
    return job["result"]["metrics"]
