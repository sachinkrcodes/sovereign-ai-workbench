import React from "react";
import { createRoot } from "react-dom/client";
import App from "./App.jsx";
import { initTheme } from "./ui.jsx";
import "./design.css";
import "./app.css";
initTheme();
createRoot(document.getElementById("root")).render(<App />);
