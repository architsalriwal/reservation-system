import axios from "axios";

// Single axios instance used everywhere in this app. The old project had
// three divergent HTTP clients (api.js, a separate CartContext instance, and
// raw axios in Cart.jsx) each with their own auth story, and only one of
// them actually attached the auth token. Every request in this app - cart,
// checkout, auth, orders - goes through this one client instead.

// This variable IS the "in memory, not localStorage" storage mentioned
// throughout the auth flow. It's just a plain JS variable living in this
// module - nothing fancier than that. Its lifetime is exactly the lifetime
// of this loaded page: a refresh, a closed tab, or navigating away and back
// resets it to null. That's deliberate (see the file-level flow map in
// firebase.js) - it's why auth.js's restoreSession() has to re-fetch a
// token on every page load instead of finding an old one sitting here.
let accessToken = null;

export function setAccessToken(token) {
  accessToken = token;
}

export function getAccessToken() {
  return accessToken;
}

const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL,
  withCredentials: true, // carries the session cookie backing the cart
});

// FLOW STEP 3: this runs before every single outgoing request made through
// `api`, anywhere in the app. If we have an access token in memory, attach
// it as the standard "Authorization: Bearer <token>" header so the backend
// knows who's making this request (see SIMPLE_JWT / JWTAuthentication on
// the backend, which reads this exact header).
api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

// Prevents a pile of simultaneous 401s (e.g. 3 components all fetching data
// at once right as the token expires) from each independently firing their
// own refresh call - they all share this one in-flight promise instead, so
// the backend only sees one refresh request, not three.
let refreshPromise = null;

// FLOW STEP 5: this runs whenever ANY request made through `api` comes back
// with an error response - but it only acts when that error is specifically
// a 401 ("your access token is missing/expired") on a request that hasn't
// already been retried once, and isn't the refresh call itself (that
// exclusion matters: without it, a refresh call that itself 401s - e.g. the
// refresh cookie expired too - would try to "refresh" forever in a loop).
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const isRefreshCall = config.url === "/auth/token/refresh/";
    if (response?.status === 401 && !config._retried && !isRefreshCall) {
      config._retried = true;
      try {
        // Same refresh endpoint restoreSession() uses on page load (auth.js
        // STEP 0) - here it's used mid-session, the moment an access token
        // actually expires (15 minutes after login, per SIMPLE_JWT on the
        // backend). The httpOnly refresh cookie is sent automatically by
        // the browser (withCredentials: true) - this code never sees or
        // touches its value directly.
        if (!refreshPromise) {
          refreshPromise = api
            .post("/auth/token/refresh/", {}, { withCredentials: true })
            .finally(() => {
              refreshPromise = null;
            });
        }
        const { data } = await refreshPromise;
        // Got a brand new access token - store it (so future requests use
        // it automatically via STEP 3 above) and also attach it directly to
        // THIS failed request, then replay that exact request. The original
        // caller never sees the 401 at all - to them, the request just
        // took a little longer and then succeeded.
        setAccessToken(data.access);
        config.headers.Authorization = `Bearer ${data.access}`;
        return api(config);
      } catch {
        // The refresh itself failed - the refresh cookie is gone/expired/
        // revoked too. There's no way to recover; drop the stale access
        // token so the app treats the user as logged out.
        setAccessToken(null);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
