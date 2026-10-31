// useState: Stores values that can change, such as email, password, and errors.
// useEffect: Runs code after React renders the component.
import { useEffect, useState } from "react";

// useNavigate: Allows us to navigate to another page using JavaScript.
import { useNavigate } from "react-router-dom";

// useAuth: Gives us access to authentication functions and login status.
import { useAuth } from "../context/AuthContext";

export default function Login() {
  // Get authentication functions and the current login status from AuthContext.
  //
  // loginWithGoogle: Logs in using a Google account.
  // loginWithEmailAndPassword: Logs in using email and password.
  // signUpWithEmailAndPassword: Creates a new account using email and password.
  // isAuthenticated: true if the user is logged in, otherwise false.
  const {
    loginWithGoogle,
    loginWithEmailAndPassword,
    signUpWithEmailAndPassword,
    isAuthenticated,
  } = useAuth();

  // Allows us to navigate to another route, such as the home page ("/").
  const navigate = useNavigate();

  // Store the email and password entered by the user.
  // Initially, both values are empty strings.
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");

  // Store an error message if login or registration fails.
  // Initially, there is no error, so the value is null.
  const [error, setError] = useState(null);

  // Track whether a login or registration request is in progress.
  // This helps us disable buttons and prevent repeated submissions.
  const [submitting, setSubmitting] = useState(false);

  // useEffect runs after React renders the component.
  //
  // If the user is already logged in, redirect them to the home page.
  // We use useEffect because navigation changes the router's state.
  // Performing that change directly during rendering is not recommended.
  useEffect(() => {
    if (isAuthenticated) {
      navigate("/");
    }
  }, [isAuthenticated, navigate]);

  // If the user is already authenticated, don't display the login form.
  // The useEffect above will redirect them to the home page.
  if (isAuthenticated) {
    return null;
  }

  // A reusable function for handling login and registration operations.
  //
  // Instead of writing the same error-handling logic three times,
  // we pass the required authentication function as an argument.
  //
  // For example:
  // withErrorHandling(() => loginWithEmailAndPassword(email, password))
  async function withErrorHandling(action) {
    // Clear any previous error before starting a new attempt.
    setError(null);

    // Mark the operation as in progress.
    setSubmitting(true);

    try {
      // Execute the authentication function passed to this helper.
      // await waits for the asynchronous operation to finish.
      await action();

      // If authentication succeeds, redirect to the home page.
      navigate("/");
    } catch (err) {
      // If authentication fails, display the error message.
      // If the error has no message, show a default message instead.
      setError(err.message ?? "Login failed.");
    } finally {
      // This block runs whether the operation succeeds or fails.
      // Re-enable the buttons by marking the operation as finished.
      setSubmitting(false);
    }
  }

  return (
    <div className="auth-shell">
      <div className="auth-card">
        <h1>Welcome back</h1>

        <p className="auth-sub">
          Sign in to check out and track your orders live.
        </p>

        {/* Display the error message only when an error exists. */}
        {error && <p className="error">{error}</p>}

        {/*
          Handle email-and-password login when the form is submitted.
          e.preventDefault() prevents the browser from refreshing the page.
        */}
        <form
          onSubmit={(e) => {
            e.preventDefault();

            // Pass the login operation to our reusable error handler.
            // The arrow function delays the login call until submission.
            withErrorHandling(() =>
              loginWithEmailAndPassword(email, password)
            );
          }}
        >
          <div className="field">
            <label htmlFor="email">Email</label>

            {/*
              This is a controlled input.
              Its value comes from React state, and onChange updates that state.
            */}
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

            {/*
              type="password" hides the entered characters.
              value and onChange keep the input synchronized with React state.
            */}
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
            {/*
              type="submit" triggers the form's onSubmit handler.
              The button is disabled while an authentication request is running.
            */}
            <button
              className="btn btn-primary btn-block"
              type="submit"
              disabled={submitting}
            >
              {/* Show different text depending on whether login is in progress. */}
              {submitting ? "Signing in..." : "Sign in"}
            </button>

            {/*
              This button creates a new account instead of logging in.
              type="button" prevents it from submitting the form normally.
            */}
            <button
              className="btn btn-secondary btn-block"
              type="button"
              disabled={submitting}
              onClick={() =>
                withErrorHandling(() =>
                  signUpWithEmailAndPassword(email, password)
                )
              }
            >
              Create an account
            </button>
          </div>
        </form>

        {/* A visual separator between email login and Google login. */}
        <div className="auth-divider">or</div>

        {/*
          Google authentication doesn't require submitting the email form.
          We pass loginWithGoogle to the same error-handling function.
        */}
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
