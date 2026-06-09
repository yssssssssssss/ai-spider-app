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
export const interpretRequest = (data: any) => api.post('/requests/interpret', data);
export const createRequest = (data: any) => api.post('/requests', data);
export const getRequest = (id: string) => api.get(`/requests/${id}`);
export const searchImages = (data: any) => api.post('/search', data);
export const listAdminRequests = (params?: any) => api.get('/admin/requests', { params });
export const getAdminStats = () => api.get('/admin/stats');
export const approveRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/approve`, data);
export const rejectRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/reject`, data);
export const listAdminTasks = (params?: any) => api.get('/admin/tasks', { params });
export const publishTaskToBlackboard = (id: string) => api.post(`/admin/tasks/${id}/blackboard`);
export const unpublishTaskFromBlackboard = (id: string) => api.delete(`/admin/tasks/${id}/blackboard`);
export const runTask = (id: string, data?: any) => api.post(`/admin/tasks/${id}/run`, data || {});
export const retryTask = (id: string, data?: any) => api.post(`/admin/tasks/${id}/retry`, data || {});
export const listTaskRuns = (id: string) => api.get(`/admin/tasks/${id}/runs`);
export const getTaskRunLogs = (id: string) => api.get(`/admin/task-runs/${id}/logs`);
export const getTaskProgress = (id: string) => api.get(`/admin/tasks/${id}/progress`);
export const getTaskImages = (id: string, params?: any) => api.get(`/admin/tasks/${id}/images`, { params });
export const getComparisonGroupByTask = (id: string) => api.get(`/comparison-groups/by-task/${id}`, { validateStatus: status => status === 200 || status === 404 });
export const exportTaskUrl = (id: string, format: 'json' | 'xlsx' | 'zip') => withToken(`/api/admin/tasks/${id}/export?format=${format}`);
export const listBlackboard = (params?: any) => api.get('/blackboard', { params });
export const getBlackboardTask = (id: string) => api.get(`/blackboard/tasks/${id}`);
export const listBlackboardTaskRuns = (id: string) => api.get(`/blackboard/tasks/${id}/runs`);
export const getBlackboardTaskImages = (id: string, params?: any) => api.get(`/blackboard/tasks/${id}/images`, { params });
export const blackboardImageFileUrl = (id: string) => `/api/blackboard/images/${id}/file`;
export const createImage = (data: any) => api.post('/images', data);
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
export const listAnalysisSkills = () => api.get('/analysis-skills');
export const createAnalysisSkill = (data: any) => api.post('/analysis-skills', data);
export const updateAnalysisSkill = (id: string, data: any) => api.patch(`/analysis-skills/${id}`, data);
export const deleteAnalysisSkill = (id: string) => api.delete(`/analysis-skills/${id}`);
export const uploadAnalysisSkillMd = (file: File) => {
  const form = new FormData();
  form.append('file', file);
  return api.post('/analysis-skills/upload-md', form, { headers: { 'Content-Type': 'multipart/form-data' } });
};
export const listAdminAnalysisSkills = () => api.get('/admin/analysis-skills');
export const createAdminAnalysisSkill = (data: any) => api.post('/admin/analysis-skills', data);
export const adminUpdateAnalysisSkill = (id: string, data: any) => api.patch(`/admin/analysis-skills/${id}`, data);
export const adminDeleteAnalysisSkill = (id: string) => api.delete(`/admin/analysis-skills/${id}`);
export const setAnalysisSkillOfficial = (id: string, is_official: boolean) => api.patch(`/admin/analysis-skills/${id}/official`, { is_official });

export default api;
