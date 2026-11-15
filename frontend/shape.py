"""Trim a rag.ask() response to what the browser needs."""


def shape(ans: dict) -> dict:
    return {
        "answer": ans.get("answer"),
        "sources": ans.get("sources", []),
        "evidence": ans.get("evidence", []),
        "conditions": ans.get("conditions") or [],
        "conditions_available": ans.get("conditions_available"),
        "gaps": ans.get("gaps", []),
        "coverage": ans.get("coverage"),
        "completeness": ans.get("completeness"),
        "grounding": ans.get("grounding"),
    }
