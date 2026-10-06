// The homepage - a read-only list of products, each with an "Add to cart"
// button. BEGINNER NOTE: every "available" number shown here comes
// straight from GET /api/products/, read ONCE when the page loads (see
// the useEffect below) - it's a snapshot, not a live, constantly-updating
// number. By the time someone actually clicks "Checkout" a minute later,
// the real number could be different - that's completely fine, because
// this page's job is only to inform, never to guarantee. The one place
// that actually enforces availability is checkout
// (backend/apps/orders/services.py's begin_checkout()).

import { useEffect, useState } from "react";

import api from "../services/api";
import { useCart } from "../context/CartContext";
import { formatINR } from "../utils/currency";

// A small presentational helper - given a number, decide what (if
// anything) to show. Returning `null` from a React component means
// "render nothing here," used below when stock is comfortably high enough
// that no badge is needed at all.
function StockBadge({ available }) {
  if (available <= 0) return <span className="stock-badge out">Sold out</span>;
  if (available <= 5) return <span className="stock-badge low">Only {available} left</span>;
  return null;
}

function ProductCard({ product, onAdd }) {
  // `adding` only controls the button's own label/disabled state while
  // ITS OWN click is in flight - it's local to this one card, not shared
  // with any other product's card.
  const [adding, setAdding] = useState(false);
  const soldOut = product.available <= 0;

  async function handleAdd() {
    setAdding(true);
    try {
      // `onAdd` is CartContext's addItem, passed down from the parent
      // Catalog component below - see that file's onAdd={(id) =>
      // addItem(id, 1)} for where it's actually wired up.
      await onAdd(product.id);
    } finally {
      // `finally` runs whether the add succeeded or failed, so the button
      // never gets stuck permanently showing "Adding..." if something
      // goes wrong.
      setAdding(false);
    }
  }

  return (
    <li className="product-card">
      <div className="product-media">
        <img src={product.image_url} alt={product.name} />
        <StockBadge available={product.available} />
      </div>
      <div className="product-body">
        {product.category && <span className="product-category">{product.category.name}</span>}
        <h3>{product.name}</h3>
        <p className="product-desc">{product.description}</p>
        <div className="product-footer">
          <span className="price">{formatINR(product.price)}</span>
          <button className="btn btn-primary" disabled={soldOut || adding} onClick={handleAdd}>
            {soldOut ? "Sold out" : adding ? "Adding..." : "Add to cart"}
          </button>
        </div>
      </div>
    </li>
  );
}

export default function Catalog() {
  const [products, setProducts] = useState([]);
  const [loading, setLoading] = useState(true);
  const { addItem } = useCart();

  // Runs once when this page first loads - the empty `[]` dependency
  // array at the end is what makes this a "run only once" effect rather
  // than something that re-runs on every render.
  useEffect(() => {
    api.get("/products/").then(({ data }) => {
      // `data.results ?? data`: this project's product list endpoint can
      // return either a plain array, or an object with a `results` key
      // (typical of paginated DRF responses) - this handles both shapes
      // without the backend and frontend having to agree in advance on
      // exactly which one is in use.
      setProducts(data.results ?? data);
      setLoading(false);
    });
  }, []);

  if (loading) return <p className="center-loading">Loading catalog...</p>;

  return (
    <div className="catalog">
      <section className="hero">
        <span className="hero-eyebrow">⚡ Live flash-sale stock</span>
        <h1>Grab it before it's gone.</h1>
        <p>
          Every checkout here goes through a real concurrency-safe reservation system - stock
          only ever commits to one buyer, even when hundreds race for the same item at once.
        </p>
      </section>

      <ul className="product-grid">
        {products.map((product) => (
          <ProductCard key={product.id} product={product} onAdd={(id) => addItem(id, 1)} />
        ))}
      </ul>
    </div>
  );
}
