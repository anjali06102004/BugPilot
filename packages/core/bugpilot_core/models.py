from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl


class ScanDepth(StrEnum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"
    CUSTOM = "custom"


class TestCategory(StrEnum):
    VISUAL = "visual"
    FUNCTIONAL = "functional"
    RESPONSIVE = "responsive"
    ACCESSIBILITY = "accessibility"
    CONSOLE = "console"
    NETWORK = "network"
    NAVIGATION = "navigation"
    FORMS = "forms"
    CONTENT = "content"


class BrowserEngine(StrEnum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class FindingCategory(StrEnum):
    VISUAL = "visual"
    LAYOUT = "layout"
    OVERFLOW = "overflow"
    BROKEN_IMAGE = "broken_image"
    CONSOLE = "console"
    NETWORK = "network"
    ACCESSIBILITY = "accessibility"
    RESPONSIVE = "responsive"
    NAVIGATION = "navigation"
    FORMS = "forms"
    INTERACTION = "interaction"
    CONTENT = "content"
    FUNCTIONAL = "functional"


class FindingStatus(StrEnum):
    NEW = "new"
    VERIFIED = "verified"
    IN_REVIEW = "in_review"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FIXED = "fixed"
    REOPENED = "reopened"
    NOT_A_BUG = "not_a_bug"


class ConfidenceLabel(StrEnum):
    CONFIRMED = "confirmed"
    LIKELY = "likely"
    POSSIBLE = "possible"
    NOT_A_BUG = "not_a_bug"


class SeverityLevel(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFORMATIONAL = "informational"


class ScanStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class ActionType(StrEnum):
    CLICK = "click"
    FILL = "fill"
    SELECT = "select"
    SCROLL = "scroll"
    HOVER = "hover"
    PRESS = "press"
    NAVIGATE = "navigate"
    OPEN_MENU = "open_menu"
    SUBMIT_FORM = "submit_form"
    RESIZE = "resize"


class MascotState(StrEnum):
    IDLE = "idle"
    FLYING = "flying"
    EXPLORING = "exploring"
    INSPECTING = "inspecting"
    SUSPICIOUS = "suspicious"
    VERIFYING = "verifying"
    BUG_FOUND = "bug_found"
    SUCCESS = "success"
    ERROR = "error"


class Viewport(BaseModel):
    name: str
    width: int
    height: int


DEFAULT_VIEWPORTS = [
    Viewport(name="mobile-375", width=375, height=812),
    Viewport(name="mobile-390", width=390, height=844),
    Viewport(name="tablet-768", width=768, height=1024),
    Viewport(name="tablet-1024", width=1024, height=768),
    Viewport(name="desktop-1280", width=1280, height=720),
    Viewport(name="desktop-1440", width=1440, height=900),
]


class ScanConfig(BaseModel):
    depth: ScanDepth = ScanDepth.STANDARD
    categories: list[TestCategory] = Field(default_factory=lambda: list(TestCategory))
    browser: BrowserEngine = BrowserEngine.CHROMIUM
    viewports: list[Viewport] = Field(
        default_factory=lambda: [
            Viewport(name="desktop-1280", width=1280, height=720),
            Viewport(name="mobile-390", width=390, height=844),
        ]
    )
    max_pages: int = 10
    max_duration_seconds: int = 180
    max_actions: int = 25
    allow_destructive: bool = False
    environment: Literal["development", "staging", "production"] = "staging"


class BoundingBox(BaseModel):
    x: float
    y: float
    width: float
    height: float


class DomElement(BaseModel):
    selector: str
    fingerprint: str
    tag: str
    role: str | None = None
    text: str = ""
    href: str | None = None
    type: str | None = None
    name: str | None = None
    id: str | None = None
    visible: bool = True
    interactive: bool = False
    disabled: bool = False
    box: BoundingBox | None = None
    styles: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, str] = Field(default_factory=dict)


class EvidenceItem(BaseModel):
    kind: Literal[
        "screenshot",
        "highlighted_screenshot",
        "dom",
        "css",
        "console",
        "network",
        "action_history",
        "url",
        "viewport",
        "timestamp",
        "reproduction",
    ]
    path: str | None = None
    content: Any = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class FindingCandidate(BaseModel):
    category: FindingCategory
    title: str
    description: str
    confidence: float = Field(ge=0, le=1)
    source: str
    selector: str | None = None
    fingerprint: str | None = None
    url: str
    viewport: Viewport | None = None
    evidence: list[EvidenceItem] = Field(default_factory=list)
    expected: str | None = None
    actual: str | None = None
    steps: list[str] = Field(default_factory=list)
    error_signature: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlannedAction(BaseModel):
    type: ActionType
    selector: str | None = None
    fingerprint: str | None = None
    value: str | None = None
    url: str | None = None
    description: str
    score: float = 0
    novelty: float = 0
    importance: float = 0
    interaction_probability: float = 0
    bug_value: float = 0
    risk: float = 0
    already_tested_penalty: float = 0
    blocked_by_policy: bool = False
    policy_reason: str | None = None


class ConsoleEvent(BaseModel):
    level: str
    text: str
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    url: str | None = None
    location: str | None = None


class NetworkEvent(BaseModel):
    method: str
    url: str
    status: int | None = None
    failed: bool = False
    failure_text: str | None = None
    resource_type: str | None = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    associated_action: str | None = None


class CreateScanRequest(BaseModel):
    url: HttpUrl
    project_name: str = "Local project"
    environment: Literal["development", "staging", "production"] = "staging"
    description: str = ""
    config: ScanConfig = Field(default_factory=ScanConfig)


class ScanEvent(BaseModel):
    type: str
    session_id: str
    message: str
    mascot: MascotState = MascotState.EXPLORING
    payload: dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=datetime.utcnow)
