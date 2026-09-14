import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import api from "../services/api";
import { useAuth } from "../context/AuthContext";
import { useCart } from "../context/CartContext";
import { formatINR } from "../utils/currency";

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
      if (data.checkout_url) {
        window.location.href = data.checkout_url;
      } else {
        navigate(`/orders/${data.order.id}`);
      }
    } catch (err) {
      setError(err.response?.data?.detail ?? "Checkout failed.");
    } finally {
      setCheckingOut(false);
    }
  }

  if (cart.items.length === 0) {
    return (
      <div className="empty-state">
        <h2>Your cart is empty</h2>
        <p>Find something you like in the catalog.</p>
        <Link to="/" className="btn btn-primary" style={{ marginTop: 16 }}>
          Browse products
        </Link>
      </div>
    );
  }

  return (
    <div className="cart">
      <div className="cart-layout">
        <ul className="cart-list">
          {cart.items.map((item) => (
            <li key={item.product.id} className="cart-row">
              <img src={item.product.image_url} alt={item.product.name} />
              <div className="cart-row-info">
                <h4>{item.product.name}</h4>
                <span className="price">{formatINR(item.product.price)}</span>
              </div>
              <div className="qty-stepper">
                <button
                  type="button"
                  onClick={() => updateQuantity(item.product.id, item.quantity - 1)}
                  disabled={item.quantity <= 1}
                >
                  −
                </button>
                <span>{item.quantity}</span>
                <button type="button" onClick={() => updateQuantity(item.product.id, item.quantity + 1)}>
                  +
                </button>
              </div>
              <button className="btn btn-ghost" onClick={() => removeItem(item.product.id)}>
                Remove
              </button>
            </li>
          ))}
        </ul>

        <aside className="cart-summary">
          <h3>Order summary</h3>
          <div className="summary-row">
            <span>Items</span>
            <span>{cart.items.reduce((n, i) => n + i.quantity, 0)}</span>
          </div>
          <div className="summary-row total">
            <span>Total</span>
            <span>{formatINR(cart.total)}</span>
          </div>
          {error && <p className="error">{error}</p>}
          <button className="btn btn-primary btn-block" disabled={checkingOut} onClick={handleCheckout} style={{ marginTop: 12 }}>
            {checkingOut ? "Starting checkout..." : "Checkout"}
          </button>
        </aside>
      </div>
    </div>
  );
}
