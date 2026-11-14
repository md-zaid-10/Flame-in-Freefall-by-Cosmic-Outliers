"""Trim a rag.ask() response for the browser and drop condition values whose
column label is known to be wrong.

rag/answer.py matches condition columns by substring, so "oxygen" also matches
"CO2" columns and "flow" matches "Flow restrictor" (a hardware setting, not an
airflow speed). Showing those under the wrong name would put a false number on
screen, so the frontend drops them. The fix belongs in rag/; this is a guard.
"""
import re

_BAD = {
    "oxygen": re.compile(r"co2|\bco\b", re.I),
    "flow": re.compile(r"restrictor", re.I),
}


def clean_conditions(rows):
    out, dropped = [], 0
    for r in rows or []:
        kept = {}
        for name, cell in (r.get("conditions") or {}).items():
            bad = _BAD.get(name)
            if bad and bad.search(cell.get("column", "")):
                dropped += 1
                continue
            kept[name] = cell
        if kept:
            out.append({**r, "conditions": kept})
    return out, dropped


def shape(ans: dict) -> dict:
    conditions, dropped = clean_conditions(ans.get("conditions"))
    return {
        "answer": ans.get("answer"),
        "sources": ans.get("sources", []),
        "evidence": ans.get("evidence", []),
        "conditions": conditions,
        "conditions_dropped": dropped,
        "conditions_available": ans.get("conditions_available"),
        "gaps": ans.get("gaps", []),
        "coverage": ans.get("coverage"),
        "completeness": ans.get("completeness"),
        "grounding": ans.get("grounding"),
    }
