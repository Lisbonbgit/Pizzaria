import React, { createContext, useContext, useState, useEffect } from 'react';

const AuthContext = createContext();

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Sessão do admin em sessionStorage: só persiste enquanto o separador/
    // browser estiver aberto — ao fechar, o login cai (medida de segurança).
    const savedToken = sessionStorage.getItem('admin_token');
    const savedUser = sessionStorage.getItem('admin_user');

    if (savedToken && savedUser) {
      try {
        setToken(savedToken);
        setUser(JSON.parse(savedUser));
      } catch (e) {
        console.error('Error loading auth state:', e);
        sessionStorage.removeItem('admin_token');
        sessionStorage.removeItem('admin_user');
      }
    }
    setLoading(false);
  }, []);

  const login = (accessToken, userData) => {
    setToken(accessToken);
    setUser(userData);
    sessionStorage.setItem('admin_token', accessToken);
    sessionStorage.setItem('admin_user', JSON.stringify(userData));
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    sessionStorage.removeItem('admin_token');
    sessionStorage.removeItem('admin_user');
  };

  const getAuthHeader = () => {
    return token ? `Bearer ${token}` : '';
  };

  return (
    <AuthContext.Provider value={{
      user,
      token,
      loading,
      login,
      logout,
      getAuthHeader,
      isAuthenticated: !!token
    }}>
      {children}
    </AuthContext.Provider>
  );
};
