from bugpilot_core.detectors.accessibility import detect_accessibility
from bugpilot_core.detectors.base import PageSnapshot
from bugpilot_core.detectors.broken_images import detect_broken_images
from bugpilot_core.detectors.console import detect_console
from bugpilot_core.detectors.forms import detect_forms
from bugpilot_core.detectors.layout import detect_layout
from bugpilot_core.detectors.navigation import detect_navigation
from bugpilot_core.detectors.network import detect_network
from bugpilot_core.detectors.overflow import detect_overflow
from bugpilot_core.models import FindingCandidate, TestCategory

CATEGORY_MAP = {
    TestCategory.VISUAL: [detect_layout, detect_broken_images, detect_overflow],
    TestCategory.RESPONSIVE: [detect_overflow, detect_layout],
    TestCategory.ACCESSIBILITY: [detect_accessibility],
    TestCategory.CONSOLE: [detect_console],
    TestCategory.NETWORK: [detect_network],
    TestCategory.FORMS: [detect_forms],
    TestCategory.NAVIGATION: [],
    TestCategory.FUNCTIONAL: [detect_network, detect_console],
    TestCategory.CONTENT: [detect_broken_images],
}


def run_detectors(
    snapshot: PageSnapshot,
    categories: list[TestCategory],
    previous_url: str | None = None,
) -> list[FindingCandidate]:
    findings: list[FindingCandidate] = []
    ran: set[str] = set()
    for category in categories:
        for detector in CATEGORY_MAP.get(category, []):
            name = detector.__name__
            if name in ran:
                continue
            ran.add(name)
            findings.extend(detector(snapshot))
    if TestCategory.NAVIGATION in categories:
        findings.extend(detect_navigation(snapshot, previous_url))
    return findings
