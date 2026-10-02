import {
  GoogleAuthProvider,
  signInWithEmailAndPassword,
  signInWithPopup,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut,
} from "firebase/auth";

import api, { setAccessToken } from "./api";
import { getFirebaseAuth } from "./firebase";

// FLOW STEP 2: by the time this runs, Firebase has already confirmed the
// user's identity (step 1, below) and handed the browser a signed "Firebase
// ID token" proving who they are. That token means nothing to OUR backend
// yet - Firebase issued it, not us. This function hands that token to our
// own server (POST /auth/login/) so OUR server can verify it and, in
// exchange, issue OUR OWN login token (a JWT) that the rest of this app
// actually uses. See backend/apps/accounts/views.py FirebaseLoginView for
// the other half of this exchange.
async function exchangeFirebaseToken(auth) {
  const idToken = await auth.currentUser.getIdToken();
  const { data } = await api.post("/auth/login/", { id_token: idToken });
  // The backend's response includes our new access token - store it (see
  // api.js STEP 3 for where this gets used).
  setAccessToken(data.access);
  return data.user;
}

// FLOW STEP 1: these three functions are called when the user interacts
// with the login/signup UI. Each one talks DIRECTLY to Firebase's own
// servers first (via the Firebase JS SDK) - our backend is not involved at
// all in this part. Firebase checks the password/Google account and, if
// it's valid, the SDK's internal state now holds a signed Firebase ID
// token for this user. Then exchangeFirebaseToken() (step 2, above) is
// called to trade that token in with our own backend.
export async function loginWithGoogle() {
  const auth = getFirebaseAuth();
  await signInWithPopup(auth, new GoogleAuthProvider());
  return exchangeFirebaseToken(auth);
}

export async function loginWithEmailAndPassword(email, password) {
  const auth = getFirebaseAuth();
  await signInWithEmailAndPassword(auth, email, password);
  return exchangeFirebaseToken(auth);
}

export async function signUpWithEmailAndPassword(email, password) {
  const auth = getFirebaseAuth();
  await createUserWithEmailAndPassword(auth, email, password);
  return exchangeFirebaseToken(auth);
}

// FLOW STEP 6 (logout): the reverse of login. Tell our backend to
// invalidate the refresh cookie (see LogoutView in views.py - it
// "blacklists" it so it can never be used again even if someone captured
// it), wipe the in-memory access token, and sign out of Firebase too so a
// later login doesn't silently reuse the old Firebase session.
export async function logout() {
  await api.post("/auth/logout/").catch(() => {});
  setAccessToken(null);
  try {
    await firebaseSignOut(getFirebaseAuth());
  } catch {
    // Firebase was never initialized (no session to sign out of) - fine.
  }
}

// FLOW STEP 0 (runs once, when the app first loads - see AuthContext.jsx,
// which calls this on mount): the in-memory access token from a PREVIOUS
// visit is gone (that's the whole point of keeping it in memory, not
// localStorage - see api.js's top comment). But the httpOnly refresh
// cookie from a previous login may still be sitting in the browser,
// unreadable by JS but still automatically sent to our server. This
// function spends that cookie to get a brand new access token, so a user
// who already logged in yesterday doesn't have to log in again today.
// api.js's 401 interceptor (STEP 5) does this same "refresh" call
// automatically later, mid-session - this is only for the very first
// moment the app loads, before there's any access token to even get a 401
// on.
export async function restoreSession() {
  try {
    const { data } = await api.post("/auth/token/refresh/");
    setAccessToken(data.access);
    const me = await api.get("/auth/me/");
    return me.data;
  } catch {
    // No valid refresh cookie (never logged in, or it expired/was revoked)
    // - that's a normal, expected outcome, not an error to report.
    return null;
  }
}
