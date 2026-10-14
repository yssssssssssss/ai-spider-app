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

export type AuditPhase = 'pre' | 'post';
export type AuditStatus = 'pass' | 'fail' | 'uncertain' | 'not_applicable' | 'disabled';
export type AuditCategory = 'regressed' | 'still_open' | 'new_issue' | 'needs_confirmation' | 'fixed' | 'kept' | 'not_comparable';
export type AuditCounts = Record<string, number>;

export interface AuditProjectInput { name: string; description?: string | null }
export interface AuditProject extends AuditProjectInput {
  id: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}
export interface AuditProjectListItem extends AuditProject {
  page_count: number;
  record_counts: AuditCounts;
}
export interface AuditPageInput { name: string; business_key?: string | null }
export interface AuditPage extends AuditPageInput {
  id: string;
  project_id: string;
  created_at: string;
}
export interface AuditRecordSummary { id: string; summary_json: AuditCounts; created_at: string }
export interface AuditPageMatrix extends AuditPage {
  latest_pre: AuditRecordSummary | null;
  latest_post: AuditRecordSummary | null;
  has_baseline: boolean;
  compare_counts: AuditCounts | null;
}
export interface AuditProjectDetail extends AuditProject { pages: AuditPageMatrix[] }
export interface AuditFinding {
  rule_id: string;
  title: string;
  status: AuditStatus;
  observed: string;
  reason: string;
  evidence: { kind: 'h5_report' | 'app_images'; image_ids: string[] };
}
export interface AuditRecord extends AuditRecordSummary {
  page_id: string;
  phase: AuditPhase;
  carrier: 'h5' | 'app';
  source_kind: 'h5_import' | 'app_task_run';
  source_ref_json: Record<string, unknown>;
  spec_key: string;
  spec_version: string;
  findings_json: AuditFinding[];
  baseline_record_id: string | null;
  note: string | null;
  created_by: string | null;
}
export interface AuditComparisonRule {
  rule_id: string;
  title: string;
  category: AuditCategory;
  pre_status: string | null;
  pre_observed: string | null;
  post_status: string | null;
  post_observed: string | null;
}
export interface AuditComparison { rules: AuditComparisonRule[]; counts: AuditCounts; spec_mismatch: boolean }
export interface AuditPageDetail extends AuditPage { records: AuditRecord[]; comparison: AuditComparison | null }
export interface AuditAppRecordInput {
  task_run_id: string;
  skill_id: string;
  phase?: AuditPhase;
  baseline_record_id?: string | null;
}
export interface AuditRecordUpdate { baseline_record_id?: string | null; note?: string | null }
export interface AuditH5ImportResult { created: number; skipped: number; pages_created: number }
export interface AuditAppCandidate {
  task_run_id: string;
  task_name: string | null;
  completed_at: string | null;
  skills: { id: string; name: string; version: number }[];
}
export interface AuditDeleteResult { ok: boolean }

export const listAuditProjects = () => api.get<AuditProjectListItem[]>('/audit-projects');
export const createAuditProject = (data: AuditProjectInput) => api.post<AuditProject>('/audit-projects', data);
export const getAuditProject = (id: string) => api.get<AuditProjectDetail>(`/audit-projects/${id}`);
export const updateAuditProject = (id: string, data: Partial<AuditProjectInput>) => api.patch<AuditProject>(`/audit-projects/${id}`, data);
export const deleteAuditProject = (id: string) => api.delete<AuditDeleteResult>(`/audit-projects/${id}`);
export const createAuditPage = (id: string, data: AuditPageInput) => api.post<AuditPage>(`/audit-projects/${id}/pages`, data);
export const getAuditPage = (id: string) => api.get<AuditPageDetail>(`/audit-pages/${id}`);
export const importAuditH5 = (id: string, file: File, venueIds?: string) => {
  const data = new FormData();
  data.append('file', file);
  if (venueIds?.trim()) data.append('venue_ids', venueIds.trim().split(/[\s,，]+/).join(','));
  return api.post<AuditH5ImportResult>(`/audit-projects/${id}/imports/h5`, data, { headers: { 'Content-Type': 'multipart/form-data' } });
};
export const listAuditAppCandidates = () => api.get<AuditAppCandidate[]>('/audit-projects/app-candidates');
export const addAuditAppRecord = (id: string, data: AuditAppRecordInput) => api.post<AuditRecord>(`/audit-pages/${id}/records/app`, data);
export const updateAuditRecord = (id: string, data: AuditRecordUpdate) => api.patch<AuditRecord>(`/audit-records/${id}`, data);
export const deleteAuditRecord = (id: string) => api.delete<AuditDeleteResult>(`/audit-records/${id}`);
export const compareAuditRecords = (postId: string, preId?: string) => api.get<AuditComparison>(`/audit-records/${postId}/compare`, { params: preId ? { pre_id: preId } : undefined });

export default api;
