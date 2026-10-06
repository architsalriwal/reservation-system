import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import api, { getAccessToken } from "../services/api";
import { useAuth } from "../context/AuthContext";
import { formatINR } from "../utils/currency";

export default function OrderStatus() {
  const { orderId } = useParams();
  const [searchParams] = useSearchParams();
  const { loading: authLoading, isAuthenticated } = useAuth();
  const [order, setOrder] = useState(null);
  const [error, setError] = useState(null);
  const [liveStatus, setLiveStatus] = useState(null);
  const socketRef = useRef(null);

  // Wait for AuthContext's one-time session restore (via the refresh
  // cookie) to finish before fetching anything. On a fresh page load -
  // e.g. Stripe redirecting back here after payment - there's no access
  // token in memory yet. Firing this fetch immediately raced AuthContext's
  // own restore: both ended up calling the token-refresh endpoint near
  // simultaneously, and since refresh tokens rotate on use, whichever call
  // lost the race used an already-blacklisted cookie and failed silently
  // (no .catch() surfaced it) - leaving the page stuck on "Loading order..."
  // forever. Gating on authLoading makes AuthContext's restore the only
  // thing that ever calls the refresh endpoint on initial load.
  useEffect(() => {
    if (authLoading) return;
    if (!isAuthenticated) {
      setError("You need to be logged in to view this order.");
      return;
    }
    api
      .get(`/orders/${orderId}/`)
      .then(({ data }) => setOrder(data))
      .catch(() => setError("Could not load this order."));
  }, [orderId, authLoading, isAuthenticated]);

  // THE LIVE-UPDATE CONNECTION. Separate from the plain GET above - this
  // opens a WebSocket (a connection that stays open, unlike a normal
  // request) to backend/apps/realtime/consumers.py's OrderConsumer. The
  // `token` is attached as a URL query parameter here because browsers
  // can't attach custom headers (like the usual "Authorization: Bearer
  // ...") to a WebSocket connection request the way they can for a normal
  // HTTP request - the token has to travel some other way, and the URL is
  // the one available for it.
  useEffect(() => {
    if (authLoading || !isAuthenticated) return;
    const token = getAccessToken();
    if (!token) return;

    const wsUrl = `${import.meta.env.VITE_WS_URL}/ws/orders/${orderId}/?token=${token}`;
    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    // Fires automatically every time the SERVER sends something down this
    // connection - no polling, no repeatedly asking "has anything
    // changed?" See backend/apps/realtime/publish.py for what actually
    // triggers a message to arrive here.
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "order.status") {
        setLiveStatus(message.new_status);
      }
    };

    // The function returned from a useEffect is its CLEANUP - React calls
    // this automatically when the component unmounts (user navigates
    // away) or before this effect re-runs. Without explicitly closing the
    // socket here, the connection could be left open even after the user
    // has left this page.
    return () => socket.close();
  }, [orderId, authLoading, isAuthenticated]);

  if (error) return <p className="error">{error}</p>;
  if (!order) return <p className="center-loading">Loading order...</p>;

  // `liveStatus ?? order.status`: the `??` operator means "use the left
  // side, UNLESS it's null/undefined, in which case use the right side
  // instead." liveStatus starts out as `null` (no WebSocket message has
  // arrived yet) and only gets set once a real update comes in - until
  // then, this falls back to whatever status the initial GET request
  // already returned, so the page always shows something sensible instead
  // of a blank value while waiting for the first live update.
  const status = liveStatus ?? order.status;

  return (
    <div className="order-shell">
      {searchParams.get("success") === "true" && (
        <p className="success-banner">Payment received — thank you!</p>
      )}
      {searchParams.get("canceled") === "true" && (
        <p className="canceled-banner">Checkout was canceled.</p>
      )}

      <div className="order-card">
        <div className="order-card-header">
          <div>
            <h2>Order status</h2>
            <span className="order-id">{order.id}</span>
          </div>
          <span className={`status-pill ${status}`}>
            {liveStatus && <span className="live-dot" />}
            {status.replace("_", " ")}
          </span>
        </div>

        <ul className="order-items">
          {order.items.map((item) => (
            <li key={item.id} className="order-item-row">
              <span>
                {item.product.name} × {item.quantity}
              </span>
              <span>{formatINR(item.unit_price_snapshot * item.quantity)}</span>
            </li>
          ))}
        </ul>

        <div className="order-total">
          <span>Total</span>
          <span>{formatINR(order.total_amount)}</span>
        </div>
      </div>
    </div>
  );
}
