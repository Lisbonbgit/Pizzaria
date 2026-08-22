import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";

// Customer pages
import MenuPage from "@/pages/MenuPage";
import OrderConfirmation from "@/pages/OrderConfirmation";

// POS pages (janela própria, fora do admin — guard é device token + PIN)
import PosApp from "@/pages/pos/PosApp";

// Admin pages
import AdminLogin from "@/pages/admin/AdminLogin";
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminPos from "@/pages/admin/AdminPos";
import AdminMenu from "@/pages/admin/AdminMenu";
import AdminTables from "@/pages/admin/AdminTables";
import AdminSettings from "@/pages/admin/AdminSettings";
import AdminPrinters from "@/pages/admin/AdminPrinters";
import AdminReports from "@/pages/admin/AdminReports";
import AdminVendusLink from "@/pages/admin/AdminVendusLink";

// Context
import { CartProvider } from "@/context/CartContext";
import { AuthProvider } from "@/context/AuthContext";

// Protected Route component
const ProtectedRoute = ({ children }) => {
  const token = sessionStorage.getItem("admin_token");
  if (!token) {
    return <Navigate to="/admin/login" replace />;
  }
  return children;
};

// Redirect component for legacy QR codes
// Redirects /pedir?mesa=X to https://pedir.lenhaebrasa.com?mesa=X
const PedirRedirect = () => {
  React.useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const mesa = params.get('mesa');
    // Mesma origem: o menu do cliente vive em "/?mesa=N".
    window.location.replace(mesa ? `/?mesa=${mesa}` : '/');
  }, []);
  return null;
};

function App() {
  return (
    <AuthProvider>
      <CartProvider>
        <BrowserRouter>
          <Routes>
            {/* Customer Routes */}
            <Route path="/" element={<MenuPage />} />
            <Route path="/pedir" element={<PedirRedirect />} />
            <Route path="/pedido/:orderId" element={<OrderConfirmation />} />

            {/* POS Routes — SEM ProtectedRoute: o guard é o device token + PIN, não o JWT admin */}
            <Route path="/pos" element={<PosApp />} />

            {/* Admin Routes */}
            <Route path="/admin/login" element={<AdminLogin />} />
            <Route path="/admin" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
            <Route path="/admin/orders" element={<ProtectedRoute><AdminOrders /></ProtectedRoute>} />
            <Route path="/admin/pos" element={<ProtectedRoute><AdminPos /></ProtectedRoute>} />
            <Route path="/admin/menu" element={<ProtectedRoute><AdminMenu /></ProtectedRoute>} />
            <Route path="/admin/tables" element={<ProtectedRoute><AdminTables /></ProtectedRoute>} />
            <Route path="/admin/printers" element={<ProtectedRoute><AdminPrinters /></ProtectedRoute>} />
            <Route path="/admin/reports" element={<ProtectedRoute><AdminReports /></ProtectedRoute>} />
            <Route path="/admin/vendus-link" element={<ProtectedRoute><AdminVendusLink /></ProtectedRoute>} />
            <Route path="/admin/settings" element={<ProtectedRoute><AdminSettings /></ProtectedRoute>} />
            
            {/* Fallback */}
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          <Toaster position="top-center" richColors />
        </BrowserRouter>
      </CartProvider>
    </AuthProvider>
  );
}

export default App;
