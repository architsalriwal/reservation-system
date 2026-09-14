import { useEffect, useRef, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import api, { getAccessToken } from "../services/api";

export default function OrderStatus() {
  const { orderId } = useParams();
  const [searchParams] = useSearchParams();
  const [order, setOrder] = useState(null);
  const [liveStatus, setLiveStatus] = useState(null);
  const socketRef = useRef(null);

  useEffect(() => {
    api.get(`/orders/${orderId}/`).then(({ data }) => setOrder(data));
  }, [orderId]);

  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;

    const wsUrl = `${import.meta.env.VITE_WS_URL}/ws/orders/${orderId}/?token=${token}`;
    const socket = new WebSocket(wsUrl);
    socketRef.current = socket;

    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      if (message.type === "order.status") {
        setLiveStatus(message.new_status);
      }
    };

    return () => socket.close();
  }, [orderId]);

  if (!order) return <p>Loading order...</p>;

  const status = liveStatus ?? order.status;

  return (
    <div className="order-status">
      <h1>Order {order.id}</h1>
      {searchParams.get("success") === "true" && <p>Payment received - thank you!</p>}
      {searchParams.get("canceled") === "true" && <p>Checkout was canceled.</p>}
      <p>
        Status: <strong>{status}</strong>
        {liveStatus && <span className="live-badge"> (live)</span>}
      </p>
      <ul>
        {order.items.map((item) => (
          <li key={item.id}>
            {item.product.name} x {item.quantity}
          </li>
        ))}
      </ul>
      <p>Total: {order.total_amount}</p>
    </div>
  );
}
