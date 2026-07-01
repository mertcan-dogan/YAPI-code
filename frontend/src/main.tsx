import * as Sentry from "@sentry/react";
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { AppErrorBoundary } from "./components/AppErrorBoundary";
import "./index.css";

// Error monitoring — env-gated. With no VITE_SENTRY_DSN, Sentry is fully disabled
// and the app runs exactly as before. Errors-only: tracesSampleRate=0.0 and NO
// Session Replay (KVKK + financial-data constraint — never capture user content).
const sentryDsn = import.meta.env.VITE_SENTRY_DSN;
if (sentryDsn) {
  Sentry.init({
    dsn: sentryDsn,
    environment: import.meta.env.VITE_ENVIRONMENT || "development",
    tracesSampleRate: 0.0,
    sendDefaultPii: false,
    // Deliberately no replayIntegration / Session Replay.
  });
}

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <AppErrorBoundary>
      <App />
    </AppErrorBoundary>
  </React.StrictMode>
);
