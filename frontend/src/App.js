import React from "react";
import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";

// Customer pages
import MenuPage from "@/pages/MenuPage";
import OrderConfirmation from "@/pages/OrderConfirmation";

// Admin pages
import AdminLogin from "@/pages/admin/AdminLogin";
import AdminDashboard from "@/pages/admin/AdminDashboard";
import AdminOrders from "@/pages/admin/AdminOrders";
import AdminMenu from "@/pages/admin/AdminMenu";
import AdminTables from "@/pages/admin/AdminTables";
import AdminSettings from "@/pages/admin/AdminSettings";

// Context
import { CartProvider } from "@/context/CartContext";
import { AuthProvider } from "@/context/AuthContext";

// Protected Route component
const ProtectedRoute = ({ children }) => {
  const token = localStorage.getItem("admin_token");
  if (!token) {
    return <Navigate to="/admin/login" replace />;
  }
  return children;
};

function App() {
  return (
    <AuthProvider>
      <CartProvider>
        <BrowserRouter>
          <Routes>
            {/* Customer Routes */}
            <Route path="/" element={<MenuPage />} />
            <Route path="/pedir" element={<MenuPage />} />
            <Route path="/pedido/:orderId" element={<OrderConfirmation />} />
            
            {/* Admin Routes */}
            <Route path="/admin/login" element={<AdminLogin />} />
            <Route path="/admin" element={<ProtectedRoute><AdminDashboard /></ProtectedRoute>} />
            <Route path="/admin/orders" element={<ProtectedRoute><AdminOrders /></ProtectedRoute>} />
            <Route path="/admin/menu" element={<ProtectedRoute><AdminMenu /></ProtectedRoute>} />
            <Route path="/admin/tables" element={<ProtectedRoute><AdminTables /></ProtectedRoute>} />
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
