import axios from "axios";

// Single axios instance used everywhere in this app. The old project had
// three divergent HTTP clients (api.js, a separate CartContext instance, and
// raw axios in Cart.jsx) each with their own auth story, and only one of
// them actually attached the auth token. Every request in this app - cart,
// checkout, auth, orders - goes through this one client instead.

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

api.interceptors.request.use((config) => {
  if (accessToken) {
    config.headers.Authorization = `Bearer ${accessToken}`;
  }
  return config;
});

let refreshPromise = null;

api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const { config, response } = error;
    const isRefreshCall = config.url === "/auth/token/refresh/";
    if (response?.status === 401 && !config._retried && !isRefreshCall) {
      config._retried = true;
      try {
        if (!refreshPromise) {
          refreshPromise = api
            .post("/auth/token/refresh/", {}, { withCredentials: true })
            .finally(() => {
              refreshPromise = null;
            });
        }
        const { data } = await refreshPromise;
        setAccessToken(data.access);
        config.headers.Authorization = `Bearer ${data.access}`;
        return api(config);
      } catch {
        setAccessToken(null);
      }
    }
    return Promise.reject(error);
  }
);

export default api;
