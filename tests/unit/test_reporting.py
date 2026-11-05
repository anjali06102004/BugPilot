from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

from bugpilot_core.config import Settings
from bugpilot_core.evidence import LocalEvidenceStore
from bugpilot_core.reporting import render_markdown, render_pdf, render_zip


def report_data() -> dict:
    return {
        "generated_at": "2026-01-01T00:00:00+00:00",
        "scan": {
            "id": "scan-1",
            "start_url": "https://shop.example.com/cart",
            "status": "completed",
            "scope_type": "single_url",
            "scope": {"type": "single_url", "start_url": "https://shop.example.com/cart"},
            "scope_summary": "Single URL: https://shop.example.com/cart",
            "pages_tested": 1,
            "actions_taken": 4,
            "pages_skipped": 0,
            "model_calls": 2,
            "stop_reason": "No new states to explore",
            "error_message": None,
            "created_at": "2026-01-01T00:00:00+00:00",
            "completed_at": "2026-01-01T00:01:00+00:00",
        },
        "project": {
            "id": "p1",
            "name": "Shop",
            "website_url": "https://shop.example.com",
            "environment": "staging",
            "critical_routes": ["/checkout"],
        },
        "pages": [
            {
                "url": "https://shop.example.com/cart",
                "title": "Cart",
                "viewport": "mobile-390",
                "screenshot_path": None,
            }
        ],
        "findings": [],
        "issues": [
            {
                "id": "issue-1",
                "title": "Horizontal overflow on page",
                "summary": "The cart page scrolls sideways on mobile.",
                "description": "scrollWidth 1400 > clientWidth 390",
                "category": "overflow",
                "severity": "medium",
                "priority": "P2",
                "confidence_label": "confirmed",
                "status": "triaged",
                "url": "https://shop.example.com/cart",
                "route": "/cart",
                "component": None,
                "expected": "Content fits the viewport.",
                "actual": "Page is 1400px wide.",
                "preconditions": None,
                "reproduction_steps": ["Open /cart at 390px", "Observe horizontal scrollbar"],
                "root_cause": "A fixed-width banner.",
                "root_cause_status": "unconfirmed",
                "suggested_fix": "Use max-width: 100% on .banner",
                "business_impact": "Checkout is hard to use on phones.",
                "environment": "staging",
                "browser": "chromium",
                "viewport": "mobile-390",
                "assigned_to": None,
                "labels": [],
                "is_regression": False,
                "occurrence_count": 1,
                "first_seen_at": "2026-01-01T00:00:00+00:00",
                "last_seen_at": "2026-01-01T00:00:00+00:00",
                "last_verified_at": None,
                "occurrences": [
                    {
                        "id": "occ-1",
                        "session_id": "scan-1",
                        "url": "https://shop.example.com/cart",
                        "viewport": "mobile-390",
                        "verified": True,
                        "reproduced": True,
                        "confidence": 0.95,
                        "confidence_label": "confirmed",
                        "created_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
                "evidence": [
                    {
                        "id": "e1",
                        "kind": "screenshot",
                        "path": "data/scan-1/shot.png",
                        "content": None,
                        "redacted": True,
                    }
                ],
            }
        ],
        "finding_evidence": [],
        "stats": {
            "total_issues": 1,
            "open_issues": 1,
            "regressions": 0,
            "confirmed": 1,
            "by_severity": {"medium": 1},
            "by_priority": {"P2": 1},
        },
    }


def test_markdown_contains_real_findings_and_limitations():
    markdown = render_markdown(report_data())
    assert "Horizontal overflow on page" in markdown
    assert "https://shop.example.com/cart" in markdown
    assert "unconfirmed" in markdown
    assert "Coverage and limitations" in markdown
    assert "not a statement that the application is free of other defects" in markdown
    assert "No new states to explore" in markdown


def test_markdown_empty_scope_is_honest():
    data = report_data()
    data["issues"] = []
    data["stats"] = {
        "total_issues": 0,
        "open_issues": 0,
        "regressions": 0,
        "confirmed": 0,
        "by_severity": {},
        "by_priority": {},
    }
    markdown = render_markdown(data)
    assert "No issues were recorded" in markdown


def test_pdf_is_a_real_pdf_document():
    pdf = render_pdf(report_data())
    assert pdf.startswith(b"%PDF-")
    assert b"%%EOF" in pdf
    assert len(pdf) > 500


def test_zip_bundle_contains_report_and_evidence(tmp_path: Path):
    settings = Settings(
        evidence_dir=tmp_path,
        evidence_signing_secret="test-secret",
    )
    store = LocalEvidenceStore(settings)
    store.save("scan-1", "shot.png", b"\x89PNG\r\n\x1a\nfake")
    bundle = render_zip(report_data(), store)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = set(archive.namelist())
        assert "report.md" in names
        assert "report.pdf" in names
        assert "report-data.json" in names
        assert "evidence-manifest.json" in names
        evidence_files = [n for n in names if n.startswith("evidence/")]
        assert evidence_files == ["evidence/scan-1/shot.png"]
        manifest = json.loads(archive.read("evidence-manifest.json"))
        assert manifest[0]["issue_id"] == "issue-1"


def test_zip_deduplicates_shared_evidence(tmp_path: Path):
    settings = Settings(evidence_dir=tmp_path, evidence_signing_secret="test-secret")
    store = LocalEvidenceStore(settings)
    store.save("scan-1", "shot.png", b"\x89PNG\r\n\x1a\nfake")
    data = report_data()
    duplicate = dict(data["issues"][0])
    duplicate["id"] = "issue-2"
    duplicate["evidence"] = list(data["issues"][0]["evidence"])
    data["issues"].append(duplicate)
    bundle = render_zip(data, store)
    with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
        names = [n for n in archive.namelist() if n.startswith("evidence/")]
        assert len(names) == 1
