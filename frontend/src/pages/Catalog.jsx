import { useEffect, useState } from "react";

import api from "../services/api";
import { useCart } from "../context/CartContext";

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

  if (loading) return <p>Loading catalog...</p>;

  return (
    <div className="catalog">
      <h1>Catalog</h1>
      <ul className="product-grid">
        {products.map((product) => (
          <li key={product.id} className="product-card">
            <h3>{product.name}</h3>
            <p>{product.description}</p>
            <p>
              {product.price} {product.currency}
            </p>
            <p>{product.available > 0 ? `${product.available} in stock` : "Out of stock"}</p>
            <button disabled={product.available <= 0} onClick={() => addItem(product.id, 1)}>
              Add to cart
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
