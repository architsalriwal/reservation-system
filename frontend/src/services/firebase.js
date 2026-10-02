// ============================================================================
// AUTH FLOW MAP - read these 6 files in this order to follow one login
// end-to-end. Each file below has "FLOW STEP n" comments marking its part.
//
//   0. frontend/src/services/firebase.js   <- you are here (lazy Firebase SDK setup)
//   0. frontend/src/context/AuthContext.jsx (mounts, tries to restore a session)
//   1. frontend/src/services/auth.js        (talks to Firebase, then to OUR backend)
//   2. backend/apps/accounts/views.py       (verifies Firebase token, issues our JWT)
//   2. backend/apps/accounts/firebase.py    (the actual token verification)
//   3. frontend/src/services/api.js         (attaches the token to every request,
//                                             and silently refreshes it when it expires)
// ============================================================================

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

// FLOW STEP 0: this function is called the first time anything actually
// needs Firebase (e.g. the user clicks "Sign in"). Before that, nothing
// Firebase-related has run yet - the SDK is only set up on first use, not
// when the app loads.
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
