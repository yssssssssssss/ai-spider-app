import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' }
});

type ToastFn = (message: string, type?: 'success' | 'error' | 'warning' | 'info') => void;

let toastRef: ToastFn | null = null;

export function registerToast(fn: ToastFn) {
  toastRef = fn;
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
    return Promise.reject(error);
  }
);

export const createRequest = (data: any) => api.post('/requests', data);
export const getRequest = (id: string) => api.get(`/requests/${id}`);
export const searchImages = (data: any) => api.post('/search', data);
export const listAdminRequests = (params?: any) => api.get('/admin/requests', { params });
export const approveRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/approve`, data);
export const rejectRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/reject`, data);
export const listAdminTasks = (params?: any) => api.get('/admin/tasks', { params });
export const runTask = (id: string) => api.post(`/admin/tasks/${id}/run`);
export const getTaskProgress = (id: string) => api.get(`/admin/tasks/${id}/progress`);
export const getTaskImages = (id: string) => api.get(`/admin/tasks/${id}/images`);
export const createImage = (data: any) => api.post('/images', data);
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

export default api;
