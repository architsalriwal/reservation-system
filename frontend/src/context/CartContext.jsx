// This file is the frontend's view of the cart - it does NOT contain the
// real cart. The real cart lives server-side, in the Django session (see
// backend/apps/storefront/cart.py). Every function below is just a thin
// wrapper that calls the backend API and stores whatever the backend sends
// back - this component never invents or calculates cart contents itself,
// it only displays what the server already decided.

import { createContext, useCallback, useContext, useEffect, useState } from "react";

import api from "../services/api";

// React Context lets any component anywhere in the app read `cart` and
// call `addItem`/etc without having to manually pass them down through
// every layer of parent/child components - see useCart() below for how a
// component actually reads this.
const CartContext = createContext(null);

export function CartProvider({ children }) {
  const [cart, setCart] = useState({ items: [], total: "0.00" });
  const [loading, setLoading] = useState(true);

  // Fetches whatever the server currently thinks is in the cart. This is
  // NOT called automatically after every change below - each action
  // (addItem, updateQuantity, removeItem) already gets the updated cart
  // back directly in its own response and updates state from that, so a
  // separate refresh() call isn't needed after them. This function exists
  // for the one-time initial load (see useEffect below).
  const refresh = useCallback(async () => {
    const { data } = await api.get("/cart/");
    setCart(data);
    return data;
  }, []);

  // Runs once, when this component first mounts - loads whatever cart
  // already exists for this browser session (e.g. from an earlier visit)
  // before the user does anything at all.
  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  // Calls backend/apps/storefront/views.py's CartItemView.post(). Note
  // there is NO stock check anywhere in this function - adding to cart
  // never touches stock at all; see backend/apps/orders/services.py's
  // begin_checkout() for where the real stock check actually happens
  // (only at checkout time).
  const addItem = useCallback(
    async (productId, quantity = 1) => {
      const { data } = await api.post("/cart/items/", { product_id: productId, quantity });
      // The backend's response already contains the FULL, updated cart -
      // we just replace our local copy with it wholesale, rather than
      // trying to locally guess/compute what the new cart should look
      // like. This keeps the frontend's cart always exactly matching what
      // the server actually has.
      setCart(data);
    },
    []
  );

  const updateQuantity = useCallback(async (productId, quantity) => {
    const { data } = await api.patch(`/cart/items/${productId}/`, { quantity });
    setCart(data);
  }, []);

  const removeItem = useCallback(async (productId) => {
    const { data } = await api.delete(`/cart/items/${productId}/`);
    setCart(data);
  }, []);

  const value = { cart, loading, addItem, updateQuantity, removeItem, refresh };

  return <CartContext.Provider value={value}>{children}</CartContext.Provider>;
}

// The hook every component actually uses to read the cart or call one of
// the functions above - e.g. `const { cart, addItem } = useCart();`. The
// error below fires if a component tries to use this outside of
// <CartProvider>, which would otherwise fail silently/confusingly.
export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
