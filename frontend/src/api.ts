import axios from 'axios';

const api = axios.create({
  baseURL: '/api',
  headers: { 'Content-Type': 'application/json' }
});

export const createRequest = (data: any) => api.post('/requests', data);
export const getRequest = (id: string) => api.get(`/requests/${id}`);
export const searchImages = (data: any) => api.post('/search', data);
export const listAdminRequests = (params?: any) => api.get('/admin/requests', { params });
export const approveRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/approve`, data);
export const rejectRequest = (id: string, data: any) => api.put(`/admin/requests/${id}/reject`, data);
export const listAdminTasks = (params?: any) => api.get('/admin/tasks', { params });
export const runTask = (id: string) => api.post(`/admin/tasks/${id}/run`);
export const getTaskProgress = (id: string) => api.get(`/admin/tasks/${id}/progress`);
export const createImage = (data: any) => api.post('/images', data);

export default api;
