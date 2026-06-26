"use client";

import { Component, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
  onReset?: () => void;
}
interface State { hasError: boolean; error: string }

export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: "" };
  }

  static getDerivedStateFromError(err: Error): State {
    return { hasError: true, error: err?.message || String(err) };
  }

  componentDidCatch(error: Error, info: { componentStack: string }) {
    // 프로덕션에서는 Sentry 등 외부 로깅 서비스로 전송 가능
    console.error("[ErrorBoundary]", error, info.componentStack);
  }

  reset = () => {
    this.setState({ hasError: false, error: "" });
    this.props.onReset?.();
  };

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div className="mone-tone-danger flex min-h-[200px] flex-col items-center justify-center gap-4 rounded-2xl p-8 text-center" style={{ border: "1px solid var(--tone-border)", background: "var(--tone-bg)" }}>
          <AlertTriangle size={24} style={{ color: "var(--tone-fg)" }} aria-hidden="true" />
          <div>
            <p className="text-sm font-semibold" style={{ color: "var(--tone-fg)" }}>화면을 표시하지 못했습니다</p>
            <p className="mt-1 max-w-sm text-xs text-[var(--text-muted)]">{this.state.error}</p>
          </div>
          <button
            onClick={this.reset}
            className="rounded-lg border border-[var(--bg-border)] bg-[var(--bg-elevated)] px-4 py-2 text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
          >
            다시 시도
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
