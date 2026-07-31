import "./index.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Shell from "./components/layout/Shell";
import Dashboard from "./pages/Dashboard";
import Campaigns from "./pages/Campaigns";
import Products from "./pages/Products";
import Creatives from "./pages/Creatives";
import Signals from "./pages/Signals";
import Runtime from "./pages/Runtime";
import Risk from "./pages/Risk";
import Replay from "./pages/Replay";

const queryClient = new QueryClient();

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/campaigns", element: <Campaigns /> },
      { path: "/products", element: <Products /> },
      { path: "/creatives", element: <Creatives /> },
      { path: "/signals", element: <Signals /> },
      { path: "/runtime", element: <Runtime /> },
      { path: "/risk", element: <Risk /> },
      { path: "/replay", element: <Replay /> },
    ],
  },
  // Retained during the Stratum 2 migration (see docs/SERVICE_MODULES.md) —
  // the previous tab-based app stays reachable at /legacy until every
  // Sidebar nav item has a page and the migration is verified end-to-end.
  { path: "/legacy", element: <App /> },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);
