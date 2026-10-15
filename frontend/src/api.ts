import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' }
});
let authToken: string | null = null;

type ToastFn = (message: string, type?: 'success' | 'error' | 'warning' | 'info') => void;

let toastRef: ToastFn | null = null;

export function registerToast(fn: ToastFn) {
  toastRef = fn;
}

export function setAuthToken(token: string | null) {
  authToken = token;
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`;
  } else {
    delete api.defaults.headers.common.Authorization;
  }
}

export function getAuthToken() {
  return authToken || localStorage.getItem('ai-taobao-token');
}

function withToken(url: string) {
  const token = getAuthToken();
  if (!token) return url;
  const sep = url.includes('?') ? '&' : '?';
  return `${url}${sep}token=${encodeURIComponent(token)}`;
}

// 响应拦截器：自动把 API 错误转为 Toast 提示
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const msg = error.response?.data?.detail || error.message || '请求失败';
    if (toastRef) {
      toastRef(msg, 'error');
    } else {
      console.error('API Error:', msg);
    }
    if (error.response?.status === 401 && window.location.pathname !== '/login') {
      window.location.assign('/login');
    }
    return Promise.reject(error);
  }
);

export const login = (data: any) => api.post('/auth/login', data);
export const registerUser = (data: any) => api.post('/auth/register', data);
export const logout = () => api.post('/auth/logout');
export const getCurrentUser = () => api.get('/auth/me');
export const listUsers = (params?: any) => api.get('/admin/users', { params });
export const createUser = (data: any) => api.post('/admin/users', data);
export const updateUser = (id: string, data: any) => api.patch(`/admin/users/${id}`, data);
export const getRegistrationInviteCode = () => api.get('/admin/settings/registration-invite-code');
export const updateRegistrationInviteCode = (data: any) => api.patch('/admin/settings/registration-invite-code', data);
export const listAnalysisSkills = (params?: any) => api.get('/admin/analysis-skills', { params });
export const getAnalysisSkill = (id: string) => api.get(`/admin/analysis-skills/${id}`);
export const createAnalysisSkill = (data: any) => api.post('/admin/analysis-skills', data);
export const updateAnalysisSkill = (id: string, data: any) => api.patch(`/admin/analysis-skills/${id}`, data);
export const deleteAnalysisSkill = (id: string) => api.delete(`/admin/analysis-skills/${id}`);
export const toggleAnalysisSkill = (id: string) => api.post(`/admin/analysis-skills/${id}/toggle`);
export const uploadAnalysisSkill = (data: FormData) => api.post('/admin/analysis-skills/upload', data, { headers: { 'Content-Type': 'multipart/form-data' } });
export const createRequest = (data: any) => api.post('/requests', data);
export const parseLongImageIntent = (data: any) => api.post('/requests/long-image-intent', data);
export const getRequest = (id: string) => api.get(`/requests/${id}`);
export const searchImages = (data: any) => api.post('/search', data);
export const listAdminRequests = (params?: any) => api.get('/admin/requests', { params });
export const getAdminStats = () => api.get('/admin/stats');
export const approveRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/approve`, data);
export const rejectRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/reject`, data);
export const listAdminTasks = (params?: any) => api.get('/admin/tasks', { params });
export const updateTask = (id: string, data: any) => api.patch(`/admin/tasks/${id}`, data);
export const deleteTask = (id: string) => api.delete(`/admin/tasks/${id}`);
export const runTask = (id: string, data?: any) => api.post(`/admin/tasks/${id}/run`, data || {});
export const retryTask = (id: string, data?: any) => api.post(`/admin/tasks/${id}/retry`, data || {});
export const listTaskRuns = (id: string) => api.get(`/admin/tasks/${id}/runs`);
export const getTaskRunLogs = (id: string) => api.get(`/admin/task-runs/${id}/logs`);
export const getTaskProgress = (id: string) => api.get(`/admin/tasks/${id}/progress`);
export const getTaskImages = (id: string, params?: any) => api.get(`/admin/tasks/${id}/images`, { params });
export const exportTaskUrl = (id: string, format: 'json' | 'xlsx' | 'zip') => withToken(`/api/admin/tasks/${id}/export?format=${format}`);
export const createImage = (data: any) => api.post('/images', data);
export const getImageAnalysisHistory = (id: string) => api.get(`/images/${id}/analysis-history`);
export const listDevices = () => api.get('/admin/devices');
export const refreshDevices = () => api.post('/admin/devices/refresh');
export const listWatchPlans = (params?: any) => api.get('/admin/watch-plans', { params });
export const createWatchPlan = (data: any) => api.post('/admin/watch-plans', data);
export const getWatchPlan = (id: string) => api.get(`/admin/watch-plans/${id}`);
export const updateWatchPlan = (id: string, data: any) => api.patch(`/admin/watch-plans/${id}`, data);
export const pauseWatchPlan = (id: string) => api.post(`/admin/watch-plans/${id}/pause`);
export const resumeWatchPlan = (id: string) => api.post(`/admin/watch-plans/${id}/resume`);
export const runWatchPlanNow = (id: string) => api.post(`/admin/watch-plans/${id}/run-now`);
export const listWatchRuns = (id: string) => api.get(`/admin/watch-plans/${id}/runs`);
export const listWatchReports = (id: string, params?: any) => api.get(`/admin/watch-plans/${id}/reports`, { params });
export const listWatchSnapshots = (id: string) => api.get(`/admin/watch-runs/${id}/snapshots`);
export const exportWatchPlanUrl = (id: string, format: 'json' | 'xlsx') => withToken(`/api/admin/watch-plans/${id}/export?format=${format}`);
export const imageFileUrl = (id: string) => withToken(`/api/images/${id}/file`);
export const taskEventsUrl = (id: string) => withToken(`/api/admin/tasks/${id}/events`);
export const listComparisonAssets = () => api.get('/compare/assets');
export const createComparisonAssetFromImage = (data: any) => api.post('/compare/assets/from-image', data);
export const uploadComparisonAsset = (data: FormData) => api.post('/compare/assets/upload', data, { headers: { 'Content-Type': 'multipart/form-data' } });
export const comparisonAssetFileUrl = (id: string) => withToken(`/api/compare/assets/${id}/file`);
export const listComparisonBasket = () => api.get('/compare/basket');
export const addComparisonBasketItem = (data: any) => api.post('/compare/basket', data);
export const deleteComparisonBasketItem = (id: string) => api.delete(`/compare/basket/${id}`);
export const clearComparisonBasket = () => api.delete('/compare/basket');
export const listComparisonSkills = (params?: any) => api.get('/compare/skills', { params });
export const createComparisonSkill = (data: any) => api.post('/compare/skills', data);
export const updateComparisonSkill = (id: string, data: any) => api.patch(`/compare/skills/${id}`, data);
export const uploadComparisonSkill = (data: FormData) => api.post('/compare/skills/upload', data, { headers: { 'Content-Type': 'multipart/form-data' } });
export const deleteComparisonSkill = (id: string) => api.delete(`/compare/skills/${id}`);
export const listComparisonReports = () => api.get('/compare/reports');
export const createComparisonReport = (data: any) => api.post('/compare/reports', data);

// Audit workspace v2. Shapes follow audit_workspace.py and audit_analytics.py.
export type AuditPhase = 'pre' | 'post';
export type AuditCarrier = 'h5' | 'app';
export type AuditJobStatus = 'queued' | 'running' | 'needs_action' | 'ingesting' | 'completed' | 'failed' | 'cancelled';
export type H5AuditStep = 'preflight' | 'catalog' | 'capture' | 'profile' | 'audit' | 'report' | 'ingest';
export interface AuditJob {
  id: string; name: string; carrier: AuditCarrier; phase: AuditPhase;
  spec_version_id: string; project_id: string | null; status: AuditJobStatus;
  status_detail: string | null; input_json: Record<string, unknown>;
  executor_ref_json: { step?: string; work_dir?: string; space_id?: number | null; pid?: number | null; summary?: { gate: { blocked: number; by_reason: Record<string, number>; degraded: number }; blocked_venue_ids: string[]; hint?: string }; [key: string]: unknown };
  audit_run_id: string | null; error: string | null; created_by: string | null;
  created_at: string; updated_at: string; finished_at: string | null;
}
export interface AuditJobInput {
  name: string; carrier: AuditCarrier; phase: AuditPhase; spec_version_id: string;
  project_id?: string; input: Record<string, unknown>;
}
export type H5AuditInput = ({ catalog_url: string; catalog_dir?: never } | { catalog_dir: string; catalog_url?: never }) & { venue_ids?: string[] };
export type AuditCarrierScope = AuditCarrier | 'both';
export type AuditOutcome = 'issues' | 'needs_confirmation' | 'partial' | 'clean' | 'capture_failed';
export type AuditStatus = 'pass' | 'fail' | 'uncertain' | 'not_applicable' | 'disabled';
export type AuditCaptureReason = 'offline' | 'expired' | 'login_required' | 'other' | 'venue_lost' | 'not_ready' | 'floor_error' | 'capture_failed';
export type AuditSort = 'fail' | 'uncertain' | 'name';
export interface AuditRule {
  rule_id: string; title: string; clause: string; expected: string;
  strength: 'mandatory' | 'conditional' | 'recommended'; enabled: boolean;
  carriers: AuditCarrier[]; method: string | null; duplicate_of: string | null;
}
export interface AuditVersionRef {
  id: string; spec_id: string; version: number; label: string;
  carrier_scope: AuditCarrierScope; sha256: string; created_at: string;
}
export interface AuditVersion extends AuditVersionRef { run_count: number; enabled_rules: number }
export interface AuditVersionDetail extends AuditVersion { rules_json: AuditRule[]; source_json: Record<string, unknown> }
export interface AuditSpecInput { key: string; name: string; description?: string | null }
export interface AuditSpec extends AuditSpecInput {
  id: string; created_at: string; updated_at: string;
  latest_version: AuditVersion | null; versions: AuditVersion[];
}
export interface AuditComposition {
  total: number; outcomes: Record<AuditOutcome, number>;
  capture_reasons: Record<AuditCaptureReason, number>;
}
export interface AuditRun {
  id: string; name: string; carrier: AuditCarrier; phase: AuditPhase;
  spec_version_id: string; project_id: string | null;
  source_kind: 'h5_import' | 'app_task_run'; source_ref_json: Record<string, unknown>;
  summary_json: { targets: number; outcomes: Record<AuditOutcome, number>; capture_reasons: Record<AuditCaptureReason, number> }; created_at: string; spec_version: AuditVersionRef;
}
export interface AuditStrip { id: string; name: string; outcome: AuditOutcome; s: string }
export interface AuditPareto { rule_id: string; title: string; fail: number; uncertain: number }
export interface AuditRunDetail extends AuditRun {
  composition: AuditComposition; pareto: AuditPareto[];
  cooccurrence: { pairs: { rules: string[]; count: number }[]; shared_evidence: { rules: string[]; count: number }[]; note: string };
  strips: AuditStrip[]; rule_order: string[]; status_codes: Record<AuditStatus, string>;
  triage: {
    focus: { id: string; name: string; fail: number; uncertain: number }[];
    batches: { rule_id: string; count: number; target_ids: string[] }[];
    evidence_gaps: { rule_id: string; count: number }[];
    recapture: { total: number; offline: number; by_reason: Record<Exclude<AuditCaptureReason, 'offline'>, number> };
  };
}
export interface AuditRunUpdate { name?: string; project_id?: string | null }
export interface AuditH5RunInput {
  file: File; spec_version_id: string; name: string; phase?: AuditPhase;
  venue_ids?: string; project_id?: string;
}
export interface AuditAppRunInput {
  task_run_id: string; skill_id: string; spec_version_id: string; name: string;
  target_name: string; business_key?: string | null; phase?: AuditPhase; project_id?: string | null;
}
export interface AuditTargetBrief {
  id: string; name: string; business_key: string | null; outcome: AuditOutcome;
  fail: number; uncertain: number; capture_reason: AuditCaptureReason | null; baseline_target_id: string | null;
}
export interface AuditFinding {
  rule_id: string; title: string; status: AuditStatus; observed: string; reason: string;
  evidence: { kind: 'h5_report' | 'app_images'; image_ids: string[] };
}
export interface AuditTarget {
  id: string; run_id: string; business_key: string | null; name: string; outcome: AuditOutcome;
  capture_reason: AuditCaptureReason | null; findings_json: AuditFinding[];
  summary_json: Partial<Record<AuditStatus, number>> & { capture_detail?: { page_warnings: unknown; page_state: unknown } };
  baseline_target_id: string | null;
}
export interface AuditTargetQuery { page?: number; page_size?: number; search?: string; outcome?: AuditOutcome; sort?: AuditSort }
export interface AuditTargetList { total: number; page: number; page_size: number; items: AuditTargetBrief[] }
export interface AuditAppCandidate {
  task_run_id: string; task_name: string; completed_at: string | null;
  skills: { id: string; name: string; version: number; skill_type: string }[];
}
export type AuditStage = 'review' | 'recheck' | 'baseline' | 'post' | 'closed';
export type AuditCategory = 'fixed' | 'still_open' | 'regressed' | 'new_issue' | 'kept' | 'needs_confirmation' | 'not_comparable';
export interface AuditProjectInput { name: string; description?: string | null }
export interface AuditProject {
  id: string; name: string; description: string | null; created_at: string; updated_at: string;
}
export interface AuditPageRef { id: string; name: string; outcome: AuditOutcome }
export interface AuditProjectListItem extends AuditProject {
  page_count: number; run_count: number;
  stages: Record<AuditStage, { count: number; pages: AuditPageRef[] }>;
}
export interface AuditPageOccurrence extends AuditPageRef {
  target_id: string; baseline_target_id: string; pre_status: AuditStatus | null; post_status: AuditStatus | null;
}
export interface AuditFlowEdge { from: 'fail' | 'pass' | 'uncertain' | 'uncovered'; to: Exclude<AuditCategory, 'not_comparable'>; count: number }
export interface AuditProjectDetail extends AuditProjectListItem {
  stage_specs: Record<AuditPhase, { id: string; spec_id: string; label: string }[]>;
  clusters: {
    regressed: { total: number; items: { rule_id: string; page: AuditPageOccurrence }[] };
    systemic: { rule_id: string; count: number; pages: AuditPageRef[] }[];
    carried: { total: number; rules: { rule_id: string; count: number; pages: AuditPageOccurrence[]; fixed_pages: AuditPageOccurrence[] }[] };
    evidence_gaps: { total: number; comparison_total: number; independent_total: number; pages: (AuditPageRef & { count: number; comparison_count: number; independent_count: number })[] };
  };
  flow: { edges: AuditFlowEdge[]; counts: Record<AuditCategory, number>; not_comparable: number; linked_posts: number };
}
export interface AuditMatrixPage extends AuditPageRef {
  pre: string; post: string; delta: string;
  pre_target_id: string | null; post_target_id: string | null; baseline_target_id: string | null;
}
export type AuditRuleDistribution = Record<'fail' | 'pass' | 'uncertain' | 'uncovered', number>;
export interface AuditProjectMatrix {
  spec_version_id: string | null; rules: AuditRule[];
  clauses: { clause: string; rule_ids: string[] }[]; pages: AuditMatrixPage[];
  pre_distribution: Record<string, AuditRuleDistribution>;
  delta_codes: Record<AuditCategory, string>; status_codes: Record<AuditStatus, string>;
}
export interface AuditComparisonRule {
  rule_id: string; title: string; category: AuditCategory;
  pre_status: AuditStatus | null; post_status: AuditStatus | null;
  pre_observed: string | null; post_observed: string | null;
}
export interface AuditPageLifeline {
  id: string; name: string; stage: AuditStage; independent_check: boolean;
  timeline: (AuditTargetBrief & { run_id: string; run_name: string; phase: AuditPhase; carrier: AuditCarrier; spec_version_id: string; spec_label: string; date: string; summary: AuditTarget['summary_json']; demo: boolean })[];
  comparison: { rules: AuditComparisonRule[]; counts: Record<AuditCategory, number>; spec_mismatch: boolean } | null;
  groups: Record<'need_action' | 'needs_confirmation' | 'closed', AuditComparisonRule[]>;
}
export const listAuditSpecs = () => api.get<AuditSpec[]>('/audit-specs');
export const listAuditJobs = (params?: { project_id?: string; status?: 'active' | 'all' }) => api.get<AuditJob[]>('/audit-jobs', { params });
export const createAuditJob = (data: AuditJobInput) => api.post<AuditJob>('/audit-jobs', data);
export const continueAuditJob = (id: string) => api.post<AuditJob>(`/audit-jobs/${id}/continue`);
export const cancelAuditJob = (id: string) => api.post<AuditJob>(`/audit-jobs/${id}/cancel`);
export const recaptureFailedAuditJob = (id: string) => api.post<AuditJob>(`/audit-jobs/${id}/recapture-failed`);
export const getAuditExecutor = (id: string, carrier: AuditCarrier) => api.get<{ available: boolean; reason: string | null }>(`/audit-specs/versions/${id}/executor`, { params: { carrier } });
export const assignAuditRuns = (projectId: string, runIds: string[]) => api.post<AuditRun[]>(`/audit-projects/${projectId}/assign-runs`, { run_ids: runIds });
export const createAuditSpec = (data: AuditSpecInput) => api.post<AuditSpec>('/audit-specs', data);
export const getAuditSpec = (id: string) => api.get<AuditSpec>(`/audit-specs/${id}`);
export const getAuditSpecVersion = (id: string) => api.get<AuditVersionDetail>(`/audit-spec-versions/${id}`);
export const importAuditSpecVersion = (id: string, file: File, carrierScope: AuditCarrierScope) => {
  const data = new FormData();
  data.append('file', file); data.append('carrier_scope', carrierScope);
  return api.post<AuditVersionDetail>(`/audit-specs/${id}/versions`, data, { headers: { 'Content-Type': 'multipart/form-data' } });
};
export const listAuditRuns = (params?: { carrier?: AuditCarrier; project_id?: string; unassigned?: boolean }) => api.get<AuditRun[]>('/audit-runs', { params });
export const getAuditRun = (id: string, outcome?: AuditOutcome) => api.get<AuditRunDetail>(`/audit-runs/${id}`, { params: { outcome } });
export const updateAuditRun = (id: string, data: AuditRunUpdate) => api.patch<AuditRun>(`/audit-runs/${id}`, data);
export const deleteAuditRun = (id: string) => api.delete<{ ok: boolean }>(`/audit-runs/${id}`);
export const importAuditH5Run = ({ file, ...fields }: AuditH5RunInput) => {
  const data = new FormData(); data.append('file', file);
  Object.entries(fields).forEach(([key, value]) => { if (value) data.append(key, value); });
  return api.post<AuditRun>('/audit-runs/h5', data, { headers: { 'Content-Type': 'multipart/form-data' } });
};
export const collectAuditAppRun = (data: AuditAppRunInput) => api.post<AuditRun>('/audit-runs/app', data);
export const listAuditTargets = (id: string, params?: AuditTargetQuery) => api.get<AuditTargetList>(`/audit-runs/${id}/targets`, { params });
export const getAuditTarget = (id: string) => api.get<AuditTarget>(`/audit-targets/${id}`);
export const listAuditAppCandidates = () => api.get<AuditAppCandidate[]>('/audit-app-candidates');
export const listAuditProjects = () => api.get<AuditProjectListItem[]>('/audit-projects');
export const createAuditProject = (data: AuditProjectInput) => api.post<AuditProject>('/audit-projects', data);
export const getAuditProject = (id: string) => api.get<AuditProjectDetail>(`/audit-projects/${id}`);
export const updateAuditProject = (id: string, data: Partial<AuditProjectInput>) => api.patch<AuditProject>(`/audit-projects/${id}`, data);
export const deleteAuditProject = (id: string) => api.delete<{ ok: boolean }>(`/audit-projects/${id}`);
export const getAuditProjectMatrix = (id: string) => api.get<AuditProjectMatrix>(`/audit-projects/${id}/matrix`);
export const getAuditPageLifeline = (id: string, pageKey: string) => api.get<AuditPageLifeline>(`/audit-projects/${id}/pages/${encodeURIComponent(pageKey)}`);
export const assignAuditRun = (id: string, projectId: string | null) => updateAuditRun(id, { project_id: projectId });
export const updateAuditTargetBaseline = (id: string, baselineTargetId: string | null) => api.patch<AuditTarget>(`/audit-targets/${id}`, { baseline_target_id: baselineTargetId });

export default api;
