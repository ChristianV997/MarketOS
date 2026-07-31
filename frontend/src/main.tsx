import "./index.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import App from "./App";
import Shell from "./components/layout/Shell";
import Dashboard from "./pages/Dashboard";
import Campaigns from "./pages/Campaigns";

const queryClient = new QueryClient();

const router = createBrowserRouter([
  {
    element: <Shell />,
    children: [
      { path: "/", element: <Dashboard /> },
      { path: "/campaigns", element: <Campaigns /> },
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
