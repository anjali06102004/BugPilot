from __future__ import annotations

from typing import Any, TypedDict

from bugpilot_core.models import FindingCandidate, PlannedAction, ScanConfig, Viewport


class AgentState(TypedDict):
    session_id: str
    start_url: str
    config: dict[str, Any]
    visited_urls: list[str]
    tested_fingerprints: list[str]
    exploration_graph: dict[str, list[str]]
    pending_actions: list[dict[str, Any]]
    current_url: str
    current_viewport: dict[str, Any]
    pages_visited: int
    actions_taken: int
    findings: list[dict[str, Any]]
    last_observation_summary: str
    suspicious: bool
    should_stop: bool
    stop_reason: str
    report_markdown: str
