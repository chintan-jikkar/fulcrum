// The entry point. React "mounts" the App component into the <div id="root"> in index.html and
// from then on redraws the page whenever a component's state changes.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import "./styles.css";
import { applyMode, applyTheme, loadMode, loadTheme } from "./theme";

// Before the first paint, so the page never flashes the default colours.
applyTheme(loadTheme());
applyMode(loadMode());

createRoot(document.getElementById("root")!).render(
  // StrictMode is a development aid: it runs effects twice to surface bugs. No effect in builds.
  <StrictMode>
    <App />
  </StrictMode>,
);
