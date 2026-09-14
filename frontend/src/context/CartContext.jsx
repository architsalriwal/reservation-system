import { createContext, useCallback, useContext, useEffect, useState } from "react";

import api from "../services/api";

const CartContext = createContext(null);

export function CartProvider({ children }) {
  const [cart, setCart] = useState({ items: [], total: "0.00" });
  const [loading, setLoading] = useState(true);

  const refresh = useCallback(async () => {
    const { data } = await api.get("/cart/");
    setCart(data);
    return data;
  }, []);

  useEffect(() => {
    refresh().finally(() => setLoading(false));
  }, [refresh]);

  const addItem = useCallback(
    async (productId, quantity = 1) => {
      const { data } = await api.post("/cart/items/", { product_id: productId, quantity });
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

export function useCart() {
  const ctx = useContext(CartContext);
  if (!ctx) throw new Error("useCart must be used within CartProvider");
  return ctx;
}
