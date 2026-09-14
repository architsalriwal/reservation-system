import { createContext, useContext, useEffect, useState } from "react";

import * as authService from "../services/auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    authService.restoreSession().then((restoredUser) => {
      setUser(restoredUser);
      setLoading(false);
    });
  }, []);

  const value = {
    user,
    loading,
    isAuthenticated: !!user,
    async loginWithGoogle() {
      const loggedInUser = await authService.loginWithGoogle();
      setUser(loggedInUser);
      return loggedInUser;
    },
    async loginWithEmailAndPassword(email, password) {
      const loggedInUser = await authService.loginWithEmailAndPassword(email, password);
      setUser(loggedInUser);
      return loggedInUser;
    },
    async signUpWithEmailAndPassword(email, password) {
      const loggedInUser = await authService.signUpWithEmailAndPassword(email, password);
      setUser(loggedInUser);
      return loggedInUser;
    },
    async logout() {
      await authService.logout();
      setUser(null);
    },
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
