export type ScanScopeType = "full_site" | "single_url" | "selected_element";
export type Severity = "critical" | "high" | "medium" | "low" | "informational";
export type Priority = "P0" | "P1" | "P2" | "P3";
export type Confidence = "confirmed" | "likely" | "possible" | "not_a_bug";
export type ScanStatus =
  | "queued"
  | "running"
  | "paused"
  | "completed"
  | "failed"
  | "stopped"
  | "cancelled";

export type IssueStatus =
  | "new"
  | "triaged"
  | "confirmed"
  | "in_progress"
  | "fixed"
  | "verified"
  | "closed"
  | "needs_review"
  | "false_positive"
  | "duplicate"
  | "reopened"
  | "blocked";

export type Finding = {
  id: string;
  issue_id?: string | null;
  session_id: string;
  category: string;
  title: string;
  description: string;
  severity: Severity;
  priority: Priority;
  confidence: number;
  confidence_label: Confidence;
  status: string;
  source: string;
  url: string;
  route?: string | null;
  component?: string | null;
  selector?: string | null;
  expected?: string | null;
  actual?: string | null;
  steps?: string[];
  suggested_fix?: string | null;
  root_cause?: string | null;
  reproduced_count: number;
  verification_attempts: number;
  screenshot?: string | null;
  screenshot_path?: string | null;
  viewport?: string | null;
  priority_rationale?: string[];
  reproduced?: boolean;
  created_at?: string | null;
  evidence?: Evidence[];
  ai_disclaimer?: string | null;
};

export type Evidence = {
  id: string;
  kind: string;
  path?: string | null;
  url?: string | null;
  content?: unknown;
  redacted?: boolean;
  created_at?: string | null;
};

export type IssueTrendPoint = {
  date: string;
  new: number;
  resolved: number;
  reopened: number;
};

export type DuplicateSuggestion = {
  id: string;
  title: string;
  severity: Severity;
  priority: Priority;
  status: IssueStatus;
  is_regression: boolean;
  occurrence_count: number;
  url: string;
  score: number;
  reasons: string[];
};

export type Issue = {
  id: string;
  issue_key: string;
  project_id: string;
  title: string;
  summary: string;
  description: string;
  category: string;
  severity: Severity;
  priority: Priority;
  confidence: number;
  confidence_label: Confidence;
  status: IssueStatus;
  source: string;
  url: string;
  route?: string | null;
  component?: string | null;
  selector?: string | null;
  expected?: string | null;
  actual?: string | null;
  preconditions?: string | null;
  reproduction_steps: string[];
  root_cause?: string | null;
  root_cause_status: string;
  suggested_fix?: string | null;
  business_impact?: string | null;
  environment?: string | null;
  browser?: string | null;
  viewport?: string | null;
  assigned_to?: string | null;
  labels: string[];
  is_regression: boolean;
  occurrence_count: number;
  affected_scan_count: number;
  affected_page_count: number;
  verified_count: number;
  reopened_count: number;
  priority_rationale?: string[];
  first_seen_at?: string | null;
  last_seen_at?: string | null;
  last_verified_at?: string | null;
  occurrences?: IssueOccurrence[];
  evidence?: Evidence[];
  events?: IssueEvent[];
  verifications?: IssueVerification[];
};

export type IssueOccurrence = {
  id: string;
  issue_id: string;
  session_id: string;
  finding_id?: string | null;
  url: string;
  route?: string | null;
  viewport?: string | null;
  severity: Severity;
  priority: Priority;
  confidence: number;
  confidence_label: Confidence;
  verified: boolean;
  reproduced: boolean;
  created_at?: string | null;
};

export type IssueVerification = {
  id: string;
  verdict: "fixed" | "still_failing" | "inconclusive";
  method: string;
  notes: string;
  actions_replayed: number;
  actions_failed: number;
  created_by?: string | null;
  created_at?: string | null;
};

export type IssueEvent = {
  id: string;
  kind: string;
  from_value?: string | null;
  to_value?: string | null;
  body: string;
  author?: string | null;
  created_at?: string | null;
};

export type ScanEvent = {
  type: string;
  session_id: string;
  message: string;
  mascot: string;
  payload: Record<string, unknown>;
  timestamp: string;
};

export type Scan = {
  id: string;
  project_id: string;
  start_url: string;
  status: ScanStatus;
  scope: { type: ScanScopeType; summary: string; definition: Record<string, unknown> };
  error_message?: string | null;
  stop_reason?: string | null;
  pages_tested: number;
  pages_skipped: number;
  actions_taken: number;
  model_calls: number;
  config: Record<string, unknown>;
  created_at?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  findings?: Finding[];
  events?: ScanEvent[];
  pages?: InspectedPage[];
  actions?: ScanAction[];
  budgets?: { pages: number; actions: number; duration_seconds: number; model_calls: number };
};

export type InspectedPage = {
  id: string;
  url: string;
  title?: string | null;
  viewport_name: string;
  in_scope: boolean;
  skip_reason?: string | null;
  screenshot?: string | null;
  created_at?: string | null;
};

export type ScanAction = {
  id: string;
  type: string;
  description: string;
  selector?: string | null;
  url?: string | null;
  blocked: boolean;
  block_reason?: string | null;
  created_at?: string | null;
};

export type Project = {
  id: string;
  name: string;
  website_url: string;
  environment: string;
  description: string;
  critical_routes: string[];
  evidence_retention_days: number;
  open_issues?: number;
  scans?: number;
  created_at?: string | null;
};

export type Dashboard = {
  projects: number;
  scans: number;
  active_scans: number;
  total_issues: number;
  open_issues: number;
  regressions: number;
  verified_issues: number;
  false_positive_rate: number;
  pages_tested: number;
  by_severity: Record<string, number>;
  by_priority: Record<string, number>;
  recent_scans: { id: string; url: string; status: string; pages_tested: number; created_at?: string }[];
};