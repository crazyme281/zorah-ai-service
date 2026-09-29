import { Component, type ErrorInfo, type ReactNode } from "react";

/**
 * Catches render errors so a crash shows a readable message instead of a
 * blank screen.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Zorah crashed:", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div
        style={{
          minHeight: "100vh",
          background: "#08080a",
          color: "#f2cb6b",
          padding: "48px 24px",
          fontFamily: "system-ui, sans-serif",
        }}
      >
        <h2 style={{ margin: 0 }}>Something went wrong</h2>
        <p style={{ color: "#bbb", wordBreak: "break-word" }}>{this.state.error.message}</p>
        <button
          onClick={() => window.location.reload()}
          style={{
            marginTop: 16,
            padding: "10px 20px",
            borderRadius: 8,
            border: "none",
            background: "#d69c2e",
            color: "#08080a",
            fontWeight: 600,
          }}
        >
          Reload
        </button>
      </div>
    );
  }
}
