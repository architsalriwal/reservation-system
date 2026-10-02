import { createContext, useContext, useEffect, useState } from "react";

import * as authService from "../services/auth";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // `loading` matters a lot: other parts of the app (e.g. OrderStatus.jsx)
  // deliberately wait for this to become false before making their own API
  // calls, so they don't race restoreSession()'s own refresh-token call
  // below and accidentally use an already-spent refresh cookie.
  const [loading, setLoading] = useState(true);

  // FLOW STEP 0: the very first thing that happens when the app loads (see
  // auth.js's restoreSession for the full explanation of why this exists).
  useEffect(() => {
    authService.restoreSession().then((restoredUser) => {
      setUser(restoredUser);
      setLoading(false);
    });
  }, []);

  // Everything below just wraps auth.js's functions (step 1/2/6) so React
  // components can call them and automatically get `user`/`isAuthenticated`
  // updated afterward - this file has no login logic of its own.
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
