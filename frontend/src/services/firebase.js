import { initializeApp } from "firebase/app";
import { getAuth } from "firebase/auth";

const firebaseConfig = {
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
};

// Lazy singleton: getAuth() throws synchronously (auth/invalid-api-key) when
// the config is missing or wrong, which previously crashed the whole React
// tree at import time - even catalog browsing, which needs no auth at all.
// Deferring init until something actually tries to sign in means the rest
// of the app still works without a configured Firebase project.
let auth = null;
let authError = null;

export function getFirebaseAuth() {
  if (auth) return auth;
  if (authError) throw authError;

  try {
    const app = initializeApp(firebaseConfig);
    auth = getAuth(app);
    return auth;
  } catch (err) {
    authError = err;
    throw err;
  }
}
