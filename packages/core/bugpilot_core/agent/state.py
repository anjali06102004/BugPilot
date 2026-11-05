from __future__ import annotations

from typing import Any, TypedDict


class AgentState(TypedDict, total=False):
    session_id: str
    start_url: str
    config: dict[str, Any]
    scope_type: str
    visited_urls: list[str]
    tested_fingerprints: list[str]
    action_history: list[dict[str, Any]]
    exploration_graph: dict[str, list[str]]
    pending_actions: list[dict[str, Any]]
    current_url: str
    current_viewport: dict[str, Any]
    current_screenshot: str
    pages_visited: int
    actions_taken: int
    findings: list[dict[str, Any]]
    last_observation_summary: str
    suspicious: bool
    should_stop: bool
    stop_reason: str
    report_markdown: str
    skipped_pages: list[dict[str, Any]]
