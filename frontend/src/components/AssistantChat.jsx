import { useRef, useState } from "react";

import api from "../services/api";
import { useCart } from "../context/CartContext";

const GREETING = {
  role: "model",
  text: "Hi! I can help you find products, check an order's status, or add something to your cart. What are you looking for?",
};

export default function AssistantChat() {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([GREETING]);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const { refresh: refreshCart } = useCart();
  const listRef = useRef(null);

  async function send() {
    const text = input.trim();
    if (!text || sending) return;

    const history = messages.map(({ role, text }) => ({ role, text }));
    setMessages((m) => [...m, { role: "user", text }]);
    setInput("");
    setSending(true);

    try {
      const { data } = await api.post("/assistant/chat/", { message: text, history });
      setMessages((m) => [...m, { role: "model", text: data.reply }]);
      if (data.tool_calls?.some((call) => call.name === "add_to_cart" && !call.result?.error)) {
        refreshCart();
      }
    } catch {
      setMessages((m) => [...m, { role: "model", text: "Sorry, something went wrong. Try again?" }]);
    } finally {
      setSending(false);
      requestAnimationFrame(() => {
        listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: "smooth" });
      });
    }
  }

  return (
    <>
      <button className="assistant-fab" onClick={() => setOpen((o) => !o)} aria-label="Open shopping assistant">
        {open ? "✕" : "💬"}
      </button>

      {open && (
        <div className="assistant-panel">
          <div className="assistant-header">
            <strong>Shopping Assistant</strong>
            <span className="assistant-subtitle">Powered by Gemini · RAG search + live actions</span>
          </div>
          <div className="assistant-messages" ref={listRef}>
            {messages.map((m, i) => (
              <div key={i} className={`assistant-bubble ${m.role}`}>
                {m.text}
              </div>
            ))}
            {sending && <div className="assistant-bubble model assistant-typing">Thinking...</div>}
          </div>
          <form
            className="assistant-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              send();
            }}
          >
            <input
              type="text"
              placeholder="Ask about products or an order..."
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={sending}
            />
            <button className="btn btn-primary" type="submit" disabled={sending || !input.trim()}>
              Send
            </button>
          </form>
        </div>
      )}
    </>
  );
}
