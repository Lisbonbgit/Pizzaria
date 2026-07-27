import axios from 'axios';

const BACKEND_URL = process.env.REACT_APP_BACKEND_URL;
const API_BASE = `${BACKEND_URL}/api`;

// Create axios instance
const api = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Add auth header interceptor
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('admin_token');
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

// Response interceptor for error handling
api.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Token expired or invalid
      localStorage.removeItem('admin_token');
      localStorage.removeItem('admin_user');
      if (window.location.pathname.startsWith('/admin') && 
          window.location.pathname !== '/admin/login') {
        window.location.href = '/admin/login';
      }
    }
    return Promise.reject(error);
  }
);

// Auth API
export const authAPI = {
  login: (email, password) => 
    api.post('/auth/login', { email, password }),
  register: (email, password, name) => 
    api.post('/auth/register', { email, password, name }),
  getMe: () => 
    api.get('/auth/me')
};

// Categories API
export const categoriesAPI = {
  list: (activeOnly = false) => 
    api.get('/categories', { params: { active_only: activeOnly } }),
  create: (data) => 
    api.post('/categories', data),
  update: (id, data) => 
    api.put(`/categories/${id}`, data),
  delete: (id) => 
    api.delete(`/categories/${id}`),
  reorder: (items) =>
    api.put('/categories/reorder', items)
};

// Products API
export const productsAPI = {
  list: (categoryId = null, availableOnly = false) => 
    api.get('/products', { params: { category_id: categoryId, available_only: availableOnly } }),
  get: (id) => 
    api.get(`/products/${id}`),
  create: (data) => 
    api.post('/products', data),
  update: (id, data) => 
    api.put(`/products/${id}`, data),
  delete: (id) => 
    api.delete(`/products/${id}`),
  uploadImage: (file) => {
    const formData = new FormData();
    formData.append('file', file);
    return api.post('/products/upload-image', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    });
  },
  importVendus: () =>
    api.post('/menu/import-vendus'),
  seedIvaDefaults: () =>
    api.post('/products/iva-defaults'),
  reorder: (items) =>
    api.put('/products/reorder', items)
};

// Tables API
export const tablesAPI = {
  list: (activeOnly = false) => 
    api.get('/tables', { params: { active_only: activeOnly } }),
  get: (id) => 
    api.get(`/tables/${id}`),
  getByNumber: (number) => 
    api.get(`/tables/by-number/${number}`),
  create: (data) => 
    api.post('/tables', data),
  update: (id, data) => 
    api.put(`/tables/${id}`, data),
  delete: (id) => 
    api.delete(`/tables/${id}`),
  getQRCode: (id, baseUrl) =>
    api.get(`/tables/${id}/qrcode`, { params: { base_url: baseUrl } }),
  overview: () =>
    api.get('/tables-overview'),
  // Sessão de mesa (fluxo público do cliente por QR)
  getSession: (number) =>
    api.get(`/tables/${number}/session`),
  openSession: (number, body) =>
    api.post(`/tables/${number}/open`, body)
};

// Orders API
export const ordersAPI = {
  list: (params = {}) => 
    api.get('/orders', { params }),
  get: (id) => 
    api.get(`/orders/${id}`),
  create: (data) => 
    api.post('/orders', data),
  updateStatus: (id, status) => 
    api.put(`/orders/${id}/status`, { status }),
  markPaid: (id, paymentMethod = null) => 
    api.put(`/orders/${id}/paid`, paymentMethod ? { payment_method: paymentMethod } : {}),
  reprint: (id, printerIds = []) => 
    api.post(`/orders/${id}/reprint`, { printer_ids: printerIds })
};

// Print Jobs API
export const printJobsAPI = {
  list: (status = null) => 
    api.get('/print-jobs', { params: { status } })
};

// Reports API
export const reportsAPI = {
  getData: (date = null) =>
    api.get('/admin/report-data', { params: date ? { date } : {} }),
  sendEmail: (date = null) =>
    api.post('/admin/send-daily-report', { date }),
  getConfig: () =>
    api.get('/admin/report-config'),
  saveResendConfig: (data) =>
    api.post('/admin/resend-config', data),
  schedulerStatus: () =>
    api.get('/admin/scheduler/status'),
  schedulerEnable: () =>
    api.post('/admin/scheduler/enable'),
  schedulerDisable: () =>
    api.post('/admin/scheduler/disable'),
  testNow: () =>
    api.post('/admin/test-daily-report')
};

// Rodízio (all-you-can-eat)
export const rodizioAPI = {
  get: () => api.get('/settings/rodizio'),
  update: (data) => api.put('/settings/rodizio', data),
  public: () => api.get('/settings/rodizio/public'),
  seedDefaults: () => api.post('/products/rodizio-defaults')
};

// Settings API
export const settingsAPI = {
  getPrinter: () => 
    api.get('/settings/printer'),
  updatePrinter: (data) => 
    api.put('/settings/printer', data),
  testPrinter: () => 
    api.post('/settings/printer/test'),
  getRestaurant: () =>
    api.get('/settings/restaurant'),
  getRestaurantPublic: () =>
    api.get('/settings/restaurant/public'),
  updateRestaurant: (data) =>
    api.put('/settings/restaurant', data)
};

// Printers API
export const printersAPI = {
  list: () =>
    api.get('/printers')
};

// Dashboard API
export const dashboardAPI = {
  getStats: () => 
    api.get('/dashboard/stats')
};

// Seed API
export const seedAPI = {
  seed: () =>
    api.post('/seed')
};

// Checkout / Fecho de mesa (Vendus)
export const checkoutAPI = {
  getBill: (tableNumber) =>
    api.get(`/tables/${tableNumber}/bill`),
  paymentMethods: () =>
    api.get('/vendus/payment-methods'),
  closeTable: (tableNumber, data) =>
    api.post(`/tables/${tableNumber}/close`, data),
  printConsulta: (tableNumber) =>
    api.post(`/tables/${tableNumber}/print-consulta`),
  freeTable: (tableNumber) =>
    api.post(`/tables/${tableNumber}/free`),
  removeItem: (orderId, idx) =>
    api.post(`/orders/${orderId}/items/${idx}/void`),
  setItemDiscount: (orderId, idx, pct) =>
    api.post(`/orders/${orderId}/items/${idx}/discount`, { pct })
};

export default api;
