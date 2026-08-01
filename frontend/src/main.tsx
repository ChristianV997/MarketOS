import "./index.css";
import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import Shell from "./components/layout/Shell";
import Dashboard from "./pages/Dashboard";
import Campaigns from "./pages/Campaigns";
import Products from "./pages/Products";
import Creatives from "./pages/Creatives";
import Signals from "./pages/Signals";
import Runtime from "./pages/Runtime";
import Risk from "./pages/Risk";
import Replay from "./pages/Replay";
import Services from "./pages/Services";
import { initPosthog } from "./lib/posthog";

initPosthog(); // no-op unless VITE_POSTHOG_KEY is set — see lib/posthog.ts

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
      { path: "/services", element: <Services /> },
    ],
  },
]);
// Note: the previous tab-based App.tsx (and its exclusive-use components —
// CommandCenter, MobileCommandCenter, DesktopWorkspace, etc.) is no longer
// mounted anywhere (was reachable at /legacy during the Stratum 2
// migration, now retired). The files themselves are left in place rather
// than deleted, in case they're still wanted for reference.

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>
  </React.StrictMode>
);
