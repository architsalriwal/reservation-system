import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { loginWithGoogle, loginWithEmailAndPassword, signUpWithEmailAndPassword, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  // Navigating during render (calling navigate() directly in the component
  // body) triggers React's "Cannot update a component while rendering a
  // different component" warning, since it updates the router's state as a
  // side effect of rendering Login itself. Doing it in an effect instead
  // defers it to after render, which is what React expects.
  useEffect(() => {
    if (isAuthenticated) {
      navigate("/");
    }
  }, [isAuthenticated, navigate]);

  if (isAuthenticated) {
    return null;
  }

  async function withErrorHandling(action) {
    setError(null);
    setSubmitting(true);
    try {
      await action();
      navigate("/");
    } catch (err) {
      setError(err.message ?? "Login failed.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1>Welcome back</h1>
        <p className="auth-sub">Sign in to check out and track your orders live.</p>
        {error && <p className="error">{error}</p>}
        <form
          onSubmit={(e) => {
            e.preventDefault();
            withErrorHandling(() => loginWithEmailAndPassword(email, password));
          }}
        >
          <div className="field">
            <label htmlFor="email">Email</label>
            <input
              id="email"
              type="email"
              placeholder="you@example.com"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              required
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </div>
          <div className="auth-actions">
            <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
              {submitting ? "Signing in..." : "Sign in"}
            </button>
            <button
              className="btn btn-secondary btn-block"
              type="button"
              disabled={submitting}
              onClick={() => withErrorHandling(() => signUpWithEmailAndPassword(email, password))}
            >
              Create an account
            </button>
          </div>
        </form>
        <div className="auth-divider">or</div>
        <button
          className="btn btn-secondary btn-block"
          disabled={submitting}
          onClick={() => withErrorHandling(loginWithGoogle)}
        >
          Continue with Google
        </button>
      </div>
    </div>
  );
}
