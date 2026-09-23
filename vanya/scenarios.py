"""Высокоуровневые сценарии: заполнение договора, риски, вопрос по документу."""

from __future__ import annotations

import re
from pathlib import Path

from . import docs, extract, prompts
from .config import TEMPLATES_DIR, load_config
from .llm import LLM, LLMError

_SOURCE_HEADER = re.compile(r"=== (.+?) ===")

# Маркеры — устойчивые «корни» ключевых слов, чтобы ловить падежные формы.
_RISK_RULES: list[tuple[list[str], str, str, str, str]] = [
    (
        ["автопролонгац"],
        "автопролонгация",
        "высокий",
        "Автопролонгация договора без явного права стороны на отказ.",
        "Предусмотреть явный срок уведомления об отказе от пролонгации.",
    ),
    (
        ["односторонн"],
        "односторонний отказ",
        "высокий",
        "Право на односторонний отказ или изменение условий без согласования.",
        "Ограничить основания одностороннего отказа и уведомить заранее.",
    ),
    (
        ["срок оплат", "сроки оплат"],
        "срок оплаты",
        "средний",
        "Срок оплаты не определён или сформулирован слишком широко.",
        "Зафиксировать конкретный срок и порядок оплаты.",
    ),
    (
        ["пеня", "пени", "пеней"],
        "пеня",
        "средний",
        "Условие о пене за просрочку, размер требует проверки.",
        "Проверить размер пени на соразмерность (ст. 333 ГК РФ).",
    ),
    (
        ["неустойк"],
        "неустойка",
        "средний",
        "Условие о неустойке, размер требует проверки.",
        "Проверить размер неустойки на соразмерность (ст. 333 ГК РФ).",
    ),
    (
        ["штраф"],
        "штраф",
        "средний",
        "Условие о штрафах, основания и размеры требуют проверки.",
        "Проверить основания начисления и размеры штрафов.",
    ),
    (
        ["подсудност"],
        "подсудность",
        "низкий",
        "Оговорка о подсудности споров.",
        "Проверить, не ущемляет ли оговорка права стороны.",
    ),
]


def fill_contract(source_filename: str | None = None, out_name: str | None = None) -> dict:
    """Детерминированный конвейер: чтение → извлечение → заполнение шаблона.

    Работает без LLM. Пустой source_filename (None / "" / "-") — режим «пакет».
    """
    cfg = load_config()
    package_mode = source_filename in (None, "", "-")
    log = []
    sources: list[str] = []
    try:
        if package_mode:
            log.append("Режим «пакет»: читаю все документы рабочей папки")
            text = docs.read_folder(cfg.workspace)
            sources = _SOURCE_HEADER.findall(text)
        else:
            log.append(f"Читаю источник: {source_filename}")
            text = docs.read_document(cfg.workspace / source_filename)
            sources = [source_filename]
    except Exception as exc:
        log.append(f"Ошибка чтения источника: {exc}")
        return {
            "ok": False,
            "error": f"Не удалось прочитать источник: {exc}",
            "fields": {},
            "missing": list(extract.FIELDS),
            "log": log,
            "package_mode": package_mode,
            "sources": sources,
        }

    found = extract.extract_requisites(text)
    missing = extract.missing_fields(found)
    log.append(f"Найдено реквизитов: {len(found)}")

    template = TEMPLATES_DIR / "dogovor_template.docx"
    if not template.exists():
        log.append("Шаблон договора не найден")
        return {
            "ok": False,
            "error": "Шаблон договора не найден",
            "fields": found,
            "missing": missing,
            "log": log,
            "package_mode": package_mode,
            "sources": sources,
        }

    if out_name is None:
        out_name = "dogovor.docx" if package_mode else Path(source_filename).stem + "_dogovor.docx"
    out_path = cfg.workspace / out_name
    docs.fill_docx(template, found, out_path)
    log.append(f"Договор сохранён: {out_name}")
    return {
        "ok": True,
        "out_path": str(out_path),
        "fields": found,
        "missing": missing,
        "log": log,
        "package_mode": package_mode,
        "sources": sources,
    }


def _heuristic_risks(text: str) -> list[dict]:
    lowered = text.lower()
    risks: list[dict] = []
    for markers, punkt, level, risk, recommendation in _RISK_RULES:
        if any(marker in lowered for marker in markers):
            risks.append(
                {
                    "punkt": punkt,
                    "risk": risk,
                    "level": level,
                    "recommendation": recommendation,
                }
            )
    if not risks:
        risks.append(
            {
                "punkt": "общие",
                "risk": "Явных рисков по ключевым словам не обнаружено.",
                "level": "низкий",
                "recommendation": "Проверить договор вручную.",
            }
        )
    return risks


def find_risks(filename: str) -> dict:
    """Анализ рисков через LLM; при недоступности модели — эвристика (fallback=True)."""
    cfg = load_config()
    log = [f"Читаю документ: {filename}"]
    try:
        text = docs.read_document(cfg.workspace / filename)
    except Exception as exc:
        return {
            "ok": False,
            "summary": "",
            "risks": [],
            "log": [f"Ошибка чтения документа: {exc}"],
            "fallback": True,
        }

    snippet = text[: cfg.max_ctx_chars]
    llm = LLM(cfg)
    messages = [
        {"role": "system", "content": prompts.RISK_SYSTEM_PROMPT},
        {"role": "user", "content": f"Проанализируй договор:\n\n{snippet}"},
    ]
    try:
        data = llm.json_chat(messages, schema_hint=prompts.RISK_SCHEMA)
        risks = data.get("risks", []) if isinstance(data, dict) else []
        summary = data.get("summary", "") if isinstance(data, dict) else ""
        if not risks:
            raise LLMError("Модель не вернула список рисков")
        log.append("Риски получены от модели")
        return {
            "ok": True,
            "summary": summary,
            "risks": risks,
            "log": log,
            "fallback": False,
        }
    except LLMError as exc:
        log.append(f"Модель недоступна, использую эвристику: {exc}")
        return {
            "ok": True,
            "summary": "Эвристический анализ (модель недоступна).",
            "risks": _heuristic_risks(text),
            "log": log,
            "fallback": True,
        }


def ask(filename: str, question: str) -> dict:
    """Ответ на вопрос по документу; при сбое модели — {"ok": False, "error": ...}."""
    cfg = load_config()
    try:
        text = docs.read_document(cfg.workspace / filename)
    except Exception as exc:
        return {"ok": False, "error": f"Не удалось прочитать документ: {exc}"}

    snippet = text[: cfg.max_ctx_chars]
    llm = LLM(cfg)
    messages = [
        {"role": "system", "content": prompts.ASK_SYSTEM_PROMPT},
        {"role": "user", "content": f"Документ:\n\n{snippet}\n\nВопрос: {question}"},
    ]
    try:
        answer = llm.chat(messages).content
    except LLMError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "answer": answer}
