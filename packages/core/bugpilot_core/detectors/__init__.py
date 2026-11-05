from bugpilot_core.detectors.accessibility import detect_accessibility
from bugpilot_core.detectors.base import PageSnapshot
from bugpilot_core.detectors.broken_images import detect_broken_images
from bugpilot_core.detectors.console import detect_console
from bugpilot_core.detectors.content import detect_content
from bugpilot_core.detectors.forms import detect_forms
from bugpilot_core.detectors.layout import detect_layout
from bugpilot_core.detectors.navigation import detect_navigation
from bugpilot_core.detectors.network import detect_network
from bugpilot_core.detectors.overflow import detect_overflow
from bugpilot_core.models import FindingCandidate, TestCategory

# Deterministic detectors, grouped by the user-selected test category.
# Navigation is handled separately because it needs the previous URL.
CATEGORY_MAP = {
    TestCategory.VISUAL: [detect_layout, detect_broken_images, detect_overflow],
    TestCategory.RESPONSIVE: [detect_overflow, detect_layout, detect_content],
    TestCategory.ACCESSIBILITY: [detect_accessibility],
    TestCategory.CONSOLE: [detect_console],
    TestCategory.NETWORK: [detect_network],
    TestCategory.FORMS: [detect_forms],
    TestCategory.NAVIGATION: [detect_navigation],
    TestCategory.FUNCTIONAL: [detect_network, detect_console],
    TestCategory.CONTENT: [detect_broken_images, detect_content],
}

DETERMINISTIC_DETECTORS = (
    detect_accessibility,
    detect_broken_images,
    detect_console,
    detect_content,
    detect_forms,
    detect_layout,
    detect_navigation,
    detect_network,
    detect_overflow,
)


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
            if detector is detect_navigation:
                findings.extend(detector(snapshot, previous_url))
            else:
                findings.extend(detector(snapshot))
    return findings
