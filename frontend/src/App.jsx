import { Link, Route, Routes } from "react-router-dom";

import { AuthProvider, useAuth } from "./context/AuthContext";
import { CartProvider, useCart } from "./context/CartContext";
import Cart from "./pages/Cart";
import Catalog from "./pages/Catalog";
import Login from "./pages/Login";
import OrderStatus from "./pages/OrderStatus";

function Nav() {
  const { isAuthenticated, user, logout } = useAuth();
  const { cart } = useCart();
  const itemCount = cart.items.reduce((sum, item) => sum + item.quantity, 0);

  return (
    <header className="site-nav">
      <div className="site-nav-inner">
        <Link to="/" className="brand">
          <span className="brand-mark">R</span>
          Reservly
        </Link>
        <nav className="nav-links">
          <Link to="/">Catalog</Link>
          <Link to="/cart" className="cart-link">
            Cart
            {itemCount > 0 && <span className="cart-badge">{itemCount}</span>}
          </Link>
          {isAuthenticated ? (
            <>
              <span className="nav-user">{user.email}</span>
              <button className="btn btn-ghost" onClick={logout}>
                Log out
              </button>
            </>
          ) : (
            <Link to="/login">Log in</Link>
          )}
        </nav>
      </div>
    </header>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <CartProvider>
        <Nav />
        <main>
          <Routes>
            <Route path="/" element={<Catalog />} />
            <Route path="/cart" element={<Cart />} />
            <Route path="/login" element={<Login />} />
            <Route path="/orders/:orderId" element={<OrderStatus />} />
          </Routes>
        </main>
      </CartProvider>
    </AuthProvider>
  );
}
