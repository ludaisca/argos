import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "@/app";
import { initTokenFromLocation } from "@/lib/api";
import "./globals.css";

initTokenFromLocation();

const container = document.getElementById("root");
if (container) {
  createRoot(container).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}
