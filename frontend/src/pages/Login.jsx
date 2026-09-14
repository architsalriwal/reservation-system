import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { useAuth } from "../context/AuthContext";

export default function Login() {
  const { loginWithGoogle, loginWithEmailAndPassword, signUpWithEmailAndPassword, isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState(null);

  if (isAuthenticated) {
    navigate("/");
    return null;
  }

  async function withErrorHandling(action) {
    setError(null);
    try {
      await action();
      navigate("/");
    } catch (err) {
      setError(err.message ?? "Login failed.");
    }
  }

  return (
    <div className="login">
      <h1>Sign in</h1>
      {error && <p className="error">{error}</p>}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          withErrorHandling(() => loginWithEmailAndPassword(email, password));
        }}
      >
        <input type="email" placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)} />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
        <button type="submit">Sign in</button>
        <button type="button" onClick={() => withErrorHandling(() => signUpWithEmailAndPassword(email, password))}>
          Sign up
        </button>
      </form>
      <button onClick={() => withErrorHandling(loginWithGoogle)}>Sign in with Google</button>
    </div>
  );
}
