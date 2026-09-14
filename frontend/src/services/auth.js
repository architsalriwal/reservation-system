import {
  GoogleAuthProvider,
  signInWithEmailAndPassword,
  signInWithPopup,
  createUserWithEmailAndPassword,
  signOut as firebaseSignOut,
} from "firebase/auth";

import api, { setAccessToken } from "./api";
import { getFirebaseAuth } from "./firebase";

async function exchangeFirebaseToken(auth) {
  const idToken = await auth.currentUser.getIdToken();
  const { data } = await api.post("/auth/login/", { id_token: idToken });
  setAccessToken(data.access);
  return data.user;
}

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

export async function logout() {
  await api.post("/auth/logout/").catch(() => {});
  setAccessToken(null);
  try {
    await firebaseSignOut(getFirebaseAuth());
  } catch {
    // Firebase was never initialized (no session to sign out of) - fine.
  }
}

// Attempts to restore a session on page load using the httpOnly refresh
// cookie - api.js's 401 interceptor already knows how to do this for a
// normal request, but on first load there's no access token yet to trigger
// that path, so we do it explicitly once.
export async function restoreSession() {
  try {
    const { data } = await api.post("/auth/token/refresh/");
    setAccessToken(data.access);
    const me = await api.get("/auth/me/");
    return me.data;
  } catch {
    return null;
  }
}
