// BEGINNER MAP: this is the page where the actual checkout request gets
// fired - see handleCheckout() below. Everything that happens AFTER that
// click (the real stock lock, the Stripe redirect) is covered in
// backend/apps/orders/views.py's CheckoutView and
// backend/apps/orders/services.py's begin_checkout().

import { useRef, useState } from "react";
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

  // One key per page view, reused across retries of a checkout click
  // within that view (network hiccup, a double-click) so the backend can
  // dedupe them into a single order - see CheckoutView's docstring. A
  // fresh mount (new page visit) gets a fresh key, which is correct: that's
  // a new, deliberate checkout attempt, not a retry of the old one.
  //
  // BEGINNER NOTE on useRef: unlike useState, changing a ref's .current
  // value does NOT cause this component to re-render. That's exactly what
  // we want here - this value needs to survive across re-renders (e.g. the
  // "Starting checkout..." button label changing) but should never itself
  // trigger one. The `if (!idempotencyKeyRef.current)` check below runs on
  // every render but only actually generates a new UUID the very first
  // time, since every render after that finds .current already set.
  const idempotencyKeyRef = useRef(null);
  if (!idempotencyKeyRef.current) {
    idempotencyKeyRef.current = crypto.randomUUID();
  }

  async function handleCheckout() {
    if (!isAuthenticated) {
      // Checkout requires login (unlike browsing or adding to cart, which
      // work for anonymous visitors) - send them to log in first instead
      // of letting the request fail.
      navigate("/login");
      return;
    }
    setCheckingOut(true);
    setError(null);
    try {
      // THE ACTUAL CHECKOUT REQUEST. The Idempotency-Key header here is
      // what backend/apps/orders/views.py's CheckoutView checks first,
      // before touching any stock at all - see that file's comments for
      // the full claim-before-mutate story.
      const { data } = await api.post(
        "/checkout/",
        {},
        { headers: { "Idempotency-Key": idempotencyKeyRef.current } }
      );
      if (data.checkout_url) {
        // Stock was reserved AND Stripe gave us a payment page - leave
        // this site entirely and go there. window.location.href (not
        // React Router's navigate()) is a FULL browser navigation, the
        // same as typing the URL in manually - this is not an in-app page.
        window.location.href = data.checkout_url;
      } else {
        // Stock was reserved, but Stripe itself failed (see the circuit
        // breaker in backend/apps/orders/views.py) - the order is still
        // real, so send them to its status page instead of pretending
        // nothing happened.
        navigate(`/orders/${data.order.id}`);
      }
    } catch (err) {
      // Most commonly a 409 "Insufficient stock" from begin_checkout() -
      // `err.response?.data?.detail` reads the backend's error message if
      // one exists, falling back to a generic message if the request
      // failed in some other way (e.g. no network connection at all).
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
