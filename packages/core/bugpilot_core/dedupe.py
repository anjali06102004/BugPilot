from __future__ import annotations

from bugpilot_core.models import FindingCandidate


def finding_key(candidate: FindingCandidate) -> str:
    selector = candidate.selector or ""
    signature = candidate.error_signature or ""
    fingerprint = candidate.fingerprint or ""
    return "|".join(
        [
            candidate.url.split("?")[0],
            candidate.category.value,
            selector,
            fingerprint,
            signature,
            candidate.source,
        ]
    )


def semantic_overlap(a: FindingCandidate, b: FindingCandidate) -> bool:
    if a.category != b.category:
        return False
    if a.url.split("?")[0] != b.url.split("?")[0]:
        return False
    if a.fingerprint and b.fingerprint and a.fingerprint == b.fingerprint:
        return True
    if a.selector and b.selector and a.selector == b.selector:
        return True
    if a.error_signature and b.error_signature and a.error_signature == b.error_signature:
        return True
    title_a = set(a.title.lower().split())
    title_b = set(b.title.lower().split())
    if not title_a or not title_b:
        return False
    return len(title_a & title_b) / len(title_a | title_b) >= 0.6


def dedupe_candidates(candidates: list[FindingCandidate]) -> list[FindingCandidate]:
    merged: list[FindingCandidate] = []
    for candidate in candidates:
        existing = next((item for item in merged if semantic_overlap(item, candidate)), None)
        if not existing:
            merged.append(candidate)
            continue
        if candidate.confidence > existing.confidence:
            candidate.evidence = existing.evidence + candidate.evidence
            idx = merged.index(existing)
            merged[idx] = candidate
        else:
            existing.evidence.extend(candidate.evidence)
    return merged
