"""Optional human screening rubric, never a trained investment prediction."""
import math

DEFAULT_WEIGHTS = {"regulatory_feasibility": .20, "clinical_evidence_quality": .20,
                   "technology_differentiation": .20, "commercial_potential": .15,
                   "business_financial_viability": .15, "team_execution": .10}


def scorecard(config: dict | None = None, *, source_ids: set[str] = frozenset(), enabled: bool = False) -> dict:
    config = {} if config is None else config
    if not isinstance(config, dict) or set(config) - {"weights", "ratings", "minimum_coverage"}:
        raise ValueError("Scorecard accepts weights, ratings and minimum_coverage only")
    weights = config.get("weights", DEFAULT_WEIGHTS)
    if not isinstance(weights, dict) or set(weights) != set(DEFAULT_WEIGHTS) or any(
        type(value) not in {int, float} or not math.isfinite(value) or value < 0 for value in weights.values()) or not math.isclose(sum(weights.values()), 1, abs_tol=1e-8):
        raise ValueError("Rubric needs all six nonnegative finite weights summing to 1")
    minimum = config.get("minimum_coverage", .75)
    if type(minimum) not in {int, float} or not .5 <= minimum <= 1:
        raise ValueError("minimum_coverage must be between 0.5 and 1")
    ratings = config.get("ratings", {})
    if not isinstance(ratings, dict) or set(ratings) - set(weights):
        raise ValueError("Unknown rubric rating category")
    criteria, rated_weight, weighted = [], 0.0, 0.0
    allowed = {"score", "reason", "evidence_ids", "confidence", "missing_inputs", "reviewed_by_human", "reviewer", "evidence_verified"}
    for category, weight in weights.items():
        rating = ratings.get(category, {})
        if not isinstance(rating, dict) or set(rating) - allowed:
            raise ValueError("Invalid rating fields")
        value = rating.get("score")
        if value is not None and (type(value) not in {int, float} or not 0 <= value <= 5):
            raise ValueError("Criterion score must be null or 0–5")
        evidence = rating.get("evidence_ids", [])
        missing = rating.get("missing_inputs", [])
        if not isinstance(evidence, list) or not all(isinstance(item, str) for item in evidence) or not isinstance(missing, list) or not all(isinstance(item, str) for item in missing):
            raise ValueError("Evidence IDs and missing inputs must be lists of strings")
        confidence = rating.get("confidence", "unknown")
        if not isinstance(confidence, str) or confidence not in {"unknown", "low", "medium", "high"}:
            raise ValueError("Invalid criterion confidence")
        reason, reviewer = rating.get("reason", ""), rating.get("reviewer", "")
        if not isinstance(reason, str) or not isinstance(reviewer, str):
            raise ValueError("Rating reason and reviewer must be text")
        reviewed = rating.get("reviewed_by_human", False) is True
        verified = rating.get("evidence_verified", False) is True
        eligible = enabled and value is not None and reviewed and verified and bool(reviewer.strip()) and bool(reason.strip()) and bool(evidence) and set(evidence) <= source_ids
        if value is not None and not eligible:
            missing = [*missing, "Enabled scoring, human review/verification, named reviewer, reason and known evidence IDs are required."]
        accepted = value if eligible else None
        if accepted is not None:
            rated_weight += weight
            weighted += weight * accepted
        criteria.append(dict(category=category, weight=weight, score=accepted,
            reason=reason or "No human-reviewed criterion rating supplied.", evidence_ids=[item for item in evidence if item in source_ids],
            confidence=confidence if eligible else "unknown", missing_inputs=missing or ([] if eligible else ["Human-verified criterion evidence and rating"]),
            reviewed_by_human=reviewed, reviewer=reviewer or None, evidence_verified=verified,
            status="human_rated" if eligible else "unrated"))
    rated_weight = round(rated_weight, 8)
    mean = weighted / rated_weight if rated_weight else None
    return dict(enabled=enabled, criteria=criteria, rated_weight=round(rated_weight, 8), total_weight=1,
        coverage=round(rated_weight, 8), minimum_coverage=minimum, rated_mean_0_to_5=mean,
        screening_score_0_to_5=mean if enabled and rated_weight >= minimum else None,
        ranking_allowed=bool(enabled and rated_weight >= minimum),
        warning="Subjective analyst screening only; not a probability, calibrated forecast or investment recommendation. Low coverage withholds the screening score; null never becomes zero.")
