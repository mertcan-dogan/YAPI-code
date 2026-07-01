import * as Sentry from "@sentry/react";
import type { ReactNode } from "react";

/**
 * Last-resort UI shown when a render error escapes the React tree. Kept dead
 * simple (inline styles, no app dependencies) so it renders even if the failure
 * is in shared layout/theme code. Turkish, per product language.
 */
export function ErrorFallback() {
  return (
    <div
      role="alert"
      style={{
        minHeight: "100vh",
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: "0.75rem",
        padding: "2rem",
        textAlign: "center",
        fontFamily: "system-ui, sans-serif",
        color: "#1f2937",
      }}
    >
      <h1 style={{ fontSize: "1.25rem", fontWeight: 600, margin: 0 }}>
        Bir şeyler ters gitti — sayfayı yenileyin
      </h1>
      <p style={{ margin: 0, color: "#6b7280" }}>
        Beklenmeyen bir hata oluştu. Sorun devam ederse lütfen yöneticinizle iletişime geçin.
      </p>
      <button
        type="button"
        onClick={() => window.location.reload()}
        style={{
          marginTop: "0.5rem",
          padding: "0.5rem 1rem",
          borderRadius: "0.5rem",
          border: "none",
          background: "#2563eb",
          color: "#fff",
          fontWeight: 500,
          cursor: "pointer",
        }}
      >
        Sayfayı yenile
      </button>
    </div>
  );
}

/**
 * Wraps the app in a Sentry error boundary. The boundary catches render errors
 * and shows {@link ErrorFallback}; it reports to Sentry only if Sentry was
 * initialized (env-gated by VITE_SENTRY_DSN) — otherwise reporting is a no-op
 * and the fallback still renders.
 */
export function AppErrorBoundary({ children }: { children: ReactNode }) {
  return <Sentry.ErrorBoundary fallback={<ErrorFallback />}>{children}</Sentry.ErrorBoundary>;
}
