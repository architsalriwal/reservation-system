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

  return (
    <nav>
      <Link to="/">Catalog</Link>
      <Link to="/cart">Cart ({cart.items.length})</Link>
      {isAuthenticated ? (
        <>
          <span>{user.email}</span>
          <button onClick={logout}>Log out</button>
        </>
      ) : (
        <Link to="/login">Log in</Link>
      )}
    </nav>
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
