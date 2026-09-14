import { useEffect, useState } from "react";

import api from "../services/api";
import { useCart } from "../context/CartContext";
import { formatINR } from "../utils/currency";

function StockBadge({ available }) {
  if (available <= 0) return <span className="stock-badge out">Sold out</span>;
  if (available <= 5) return <span className="stock-badge low">Only {available} left</span>;
  return null;
}

function ProductCard({ product, onAdd }) {
  const [adding, setAdding] = useState(false);
  const soldOut = product.available <= 0;

  async function handleAdd() {
    setAdding(true);
    try {
      await onAdd(product.id);
    } finally {
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

  useEffect(() => {
    api.get("/products/").then(({ data }) => {
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
