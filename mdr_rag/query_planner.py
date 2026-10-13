"""Bounded, source-constrained retrieval intents; never legal conclusions."""
import re
from pydantic import BaseModel, ConfigDict, Field


class PlannedQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    intent: str
    text: str


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    queries: list[PlannedQuery] = Field(max_length=4, min_length=1)
    planner: str = "deterministic"
    fallback: str | None = None


class PlannerSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    selected_ids: list[str] = Field(max_length=3)


class PlannerPersistenceError(RuntimeError):
    """Storage errors must propagate rather than become planner fallbacks."""


PLANNER_RULES = "Select relevant search intents from the supplied menu. Return selected_ids only. Do not create queries, facts, obligations, classifications or jurisdictions."


def canonical(text):
    return " ".join(text.split()).casefold()


def plan_queries(requirement, profile=None, *, maximum=4, llm=None):
    if not 1 <= maximum <= 4:
        raise ValueError("Query budget must be between 1 and 4")
    original = f"{requirement.provision} {requirement.requirement} {requirement.exact_quote}"
    # Every substantive term comes from the obligation. Added words name search
    # intents, not assumed requirements or asserted evidence.
    topic = " ".join(requirement.requirement.split())
    artifacts = re.findall(r"\b(?:[\w-]+\s+){0,3}(?:records?|reports?|files?|plans?|documentation|analysis|evaluation)\b", topic, re.I)
    menu = [PlannedQuery(id="Q1", intent="original", text=original),
            PlannedQuery(id="Q2", intent="artifact", text=(" ".join(artifacts) or topic) + " document evidence"),
            PlannedQuery(id="Q3", intent="process", text=topic + " process test evidence")]
    facts = profile or {}
    qualifier = " ".join(str(facts.get(key) or "") for key in ("device_name", "intended_purpose"))
    menu.append(PlannedQuery(id="Q4", intent="qualifier", text=topic + " " + qualifier if qualifier.strip() else topic))
    selected, fallback, planner = menu[1:], None, "deterministic"
    if llm is not None and maximum > 1:
        try:
            choice = llm(PLANNER_RULES, "\n".join(f"{q.id}: {q.text}" for q in menu[1:]), PlannerSelection)
            choice = PlannerSelection.model_validate(choice)
            allowed = {q.id: q for q in menu[1:]}
            if any(key not in allowed for key in choice.selected_ids):
                raise ValueError("Unknown intent")
            selected = [allowed[key] for key in choice.selected_ids]
            planner = "llm_selection"
        except PlannerPersistenceError:
            raise
        except Exception:
            fallback = "invalid_or_failed_llm_selection"
    result, seen = [], set()
    for query in [menu[0], *selected]:
        key = canonical(query.text)
        if key and key not in seen:
            result.append(query)
            seen.add(key)
        if len(result) == maximum:
            break
    result = [q.model_copy(update={"id": f"Q{i}"}) for i, q in enumerate(result, 1)]
    return QueryPlan(queries=result, planner=planner, fallback=fallback)
