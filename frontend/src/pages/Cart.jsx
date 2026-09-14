import { useState } from "react";
import { useNavigate } from "react-router-dom";

import api from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";

export default function Cart() {
  const { cart, updateQuantity, removeItem } = useCart();
  const { isAuthenticated } = useAuth();
  const navigate = useNavigate();
  const [checkingOut, setCheckingOut] = useState(false);
  const [error, setError] = useState(null);

  async function handleCheckout() {
    if (!isAuthenticated) {
      navigate("/login");
      return;
    }
    setCheckingOut(true);
    setError(null);
    try {
      const { data } = await api.post("/checkout/");
      window.location.href = data.checkout_url;
    } catch (err) {
      setError(err.response?.data?.detail ?? "Checkout failed.");
    } finally {
      setCheckingOut(false);
    }
  }

  if (cart.items.length === 0) return <p>Your cart is empty.</p>;

  return (
    <div className="cart">
      <h1>Cart</h1>
      <ul>
        {cart.items.map((item) => (
          <li key={item.product.id}>
            <span>{item.product.name}</span>
            <input
              type="number"
              min={1}
              value={item.quantity}
              onChange={(e) => updateQuantity(item.product.id, Number(e.target.value))}
            />
            <span>{item.line_total}</span>
            <button onClick={() => removeItem(item.product.id)}>Remove</button>
          </li>
        ))}
      </ul>
      <p>Total: {cart.total}</p>
      {error && <p className="error">{error}</p>}
      <button disabled={checkingOut} onClick={handleCheckout}>
        {checkingOut ? "Starting checkout..." : "Checkout"}
      </button>
    </div>
  );
}
