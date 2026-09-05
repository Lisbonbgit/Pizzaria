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
  const token = sessionStorage.getItem('admin_token');
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
      sessionStorage.removeItem('admin_token');
      sessionStorage.removeItem('admin_user');
      if (window.location.pathname.startsWith('/admin') && 
          window.location.pathname !== '/admin/login') {
        window.location.href = '/admin/login';
      }
    }
    return Promise.reject(error);
  }
);

// Instância de axios separada para o POS (janela do POS/Caixa).
// Autentica com device token + token POS (PIN), NUNCA com o JWT do admin.
export const posApi = axios.create({
  baseURL: API_BASE,
  headers: {
    'Content-Type': 'application/json'
  }
});

// Interceptor do POS: adiciona X-Device-Token e X-POS-Token quando existirem.
// Propositadamente NÃO adiciona Authorization (essa é a instância `api`, do admin).
posApi.interceptors.request.use((config) => {
  const deviceToken = localStorage.getItem('pos_device_token');
  const posToken = localStorage.getItem('pos_token');
  if (deviceToken) {
    config.headers['X-Device-Token'] = deviceToken;
  }
  if (posToken) {
    config.headers['X-POS-Token'] = posToken;
  }
  return config;
});

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
  importAppProducts: () =>
    api.post('/admin/pos/import-app-products'),
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
  getData: (start = null, end = null) =>
    api.get('/admin/report-data', {
      params: { ...(start ? { start } : {}), ...(end ? { end } : {}) },
    }),
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
  // Resumo de todas as mesas (id/nome/pessoas/rodízio) — usado pelo
  // TableCheckout (partilhado com o POS) para inicializar/atualizar o
  // estado do rodízio sem depender da grelha do chamador.
  overview: () =>
    api.get('/tables-overview'),
  paymentMethods: () =>
    api.get('/vendus/payment-methods'),
  closeTable: (tableNumber, data) =>
    api.post(`/tables/${tableNumber}/close`, data),
  // Cancela uma divisão ainda sem nenhuma parte emitida (409 se já saiu uma).
  cancelSplit: (tableNumber) =>
    api.post(`/tables/${tableNumber}/split-cancel`),
  printConsulta: (tableNumber) =>
    api.post(`/tables/${tableNumber}/print-consulta`),
  freeTable: (tableNumber) =>
    api.post(`/tables/${tableNumber}/free`),
  // Gerir rodízio da mesa (tier + nº de pessoas) — adicionar/corrigir.
  setRodizio: (tableNumber, body) =>
    api.post(`/tables/${tableNumber}/rodizio`, body),
  removeItem: (orderId, idx) =>
    api.post(`/orders/${orderId}/items/${idx}/void`),
  // Desconto por item: corpo { pct } (%) OU { amount } (€) — mutuamente exclusivos.
  setItemDiscount: (orderId, idx, body) =>
    api.post(`/orders/${orderId}/items/${idx}/discount`, body),
  // Edita preço/quantidade/IVA de um item (diálogo do produto, Fase 3).
  editItem: (orderId, idx, data) =>
    api.post(`/orders/${orderId}/items/${idx}/edit`, data)
};

// POS - Autenticação e Caixa (via posApi: device + token PIN, sem Authorization)
export const posAPI = {
  login: (pin) =>
    posApi.post('/pos/login', { pin }),
  cashCurrent: () =>
    posApi.get('/pos/cash/current'),
  cashOpen: (opening_amount) =>
    posApi.post('/pos/cash/open', { opening_amount }),
  cashMovement: (type, amount, reason) =>
    posApi.post('/pos/cash/movement', { type, amount, reason }),
  cashClose: (counted_amount) =>
    posApi.post('/pos/cash/close', { counted_amount }),
  // Pré-visualização do dinheiro esperado no caixa (Fase 4b), para o ecrã de
  // Fechar Caixa mostrar antes do operador contar a gaveta.
  cashExpected: () =>
    posApi.get('/pos/cash/expected'),
  cashZ: (id) =>
    posApi.get(`/pos/cash/${id}/z`),
  openDrawer: () =>
    posApi.post('/pos/cash/drawer'),
  // Lista pública (device token) dos utilizadores POS ativos, {id, name} —
  // p/ a tela de bloqueio/descanso mostrar avatares sem JWT de admin.
  usersPublic: () =>
    posApi.get('/pos/users-public')
};

// POS - Checkout / mesas (mesmos caminhos do checkoutAPI/tablesAPI admin, mas via posApi)
export const posCheckout = {
  overview: () =>
    posApi.get('/tables-overview'),
  paymentMethods: () =>
    posApi.get('/vendus/payment-methods'),
  getBill: (tableNumber) =>
    posApi.get(`/tables/${tableNumber}/bill`),
  closeTable: (tableNumber, data) =>
    posApi.post(`/tables/${tableNumber}/close`, data),
  // Cancela uma divisão ainda sem nenhuma parte emitida (409 se já saiu uma).
  cancelSplit: (tableNumber) =>
    posApi.post(`/tables/${tableNumber}/split-cancel`),
  // Desconto por item: corpo { pct } (%) OU { amount } (€) — mutuamente exclusivos.
  setItemDiscount: (orderId, idx, body) =>
    posApi.post(`/orders/${orderId}/items/${idx}/discount`, body),
  // Edita preço/quantidade/IVA de um item (diálogo do produto, Fase 3).
  editItem: (orderId, idx, data) =>
    posApi.post(`/orders/${orderId}/items/${idx}/edit`, data),
  removeItem: (orderId, idx) =>
    posApi.post(`/orders/${orderId}/items/${idx}/void`),
  printConsulta: (tableNumber) =>
    posApi.post(`/tables/${tableNumber}/print-consulta`),
  freeTable: (tableNumber) =>
    posApi.post(`/tables/${tableNumber}/free`),
  // Gerir rodízio da mesa (tier + nº de pessoas) — adicionar/corrigir.
  setRodizio: (tableNumber, body) =>
    posApi.post(`/tables/${tableNumber}/rodizio`, body)
};

// POS - Balcão (pedido sem mesa: criar + faturar + catálogo p/ picker) via posApi
export const posCounter = {
  createOrder: (items) =>
    posApi.post('/pos/counter/order', { items }),
  updateOrder: (orderId, items) =>
    posApi.post(`/pos/counter/${orderId}/update`, { items }),
  checkout: (orderId, paymentMethodId, nif, splitCount) =>
    posApi.post('/pos/counter/checkout', {
      order_id: orderId,
      payment_method_id: paymentMethodId,
      nif: nif || undefined,
      // >1 divide a venda: emite UMA parte por chamada (NIF/pagamento próprios).
      split_count: splitCount && splitCount > 1 ? splitCount : undefined
    }),
  // Cancela uma divisão do balcão ainda sem nenhuma parte emitida.
  cancelSplit: (orderId) =>
    posApi.post(`/pos/counter/${orderId}/split-cancel`),
  // Cancela um pedido de balcão não faturado (para poder sair sem deixar pendente).
  cancelOrder: (orderId) =>
    posApi.post(`/pos/counter/${orderId}/cancel`),
  // Catálogo (GET /products e /categories são públicos no backend — sem
  // dependência de auth, tal como o menu do cliente por QR — por isso
  // funcionam via posApi sem exigir device token/JWT).
  products: () =>
    posApi.get('/products', { params: { available_only: true } }),
  categories: () =>
    posApi.get('/categories', { params: { active_only: true } })
};

// POS - Nota de crédito (listar faturas recentes + emitir NC de uma) via posApi
export const posCreditNote = {
  listInvoices: () =>
    posApi.get('/pos/credit-note/invoices'),
  create: (documentId) =>
    posApi.post('/pos/credit-note', { document_id: documentId })
};

// Ligação de produtos aos artigos do Vendus
export const vendusLinkAPI = {
  suggestions: () =>
    api.get('/admin/vendus/link-suggestions'),
  save: (links) =>
    api.post('/admin/vendus/link', { links })
};

// Admin - Gestão do POS (utilizadores, definições, device tokens) via api (JWT admin)
export const adminPosAPI = {
  listUsers: () =>
    api.get('/admin/pos/users'),
  createUser: (data) =>
    api.post('/admin/pos/users', data),
  updateUser: (id, data) =>
    api.put(`/admin/pos/users/${id}`, data),
  deleteUser: (id) =>
    api.delete(`/admin/pos/users/${id}`),
  getSettings: () =>
    api.get('/admin/pos/settings'),
  saveSettings: (data) =>
    api.put('/admin/pos/settings', data),
  createDeviceToken: (label, days = null) =>
    api.post('/admin/pos/device-token', days ? { label, days } : { label })
};

export default api;
