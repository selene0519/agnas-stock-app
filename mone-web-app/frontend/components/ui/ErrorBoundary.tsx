"use client";

import { Component, type ReactNode } from "react";

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
        <div className="flex min-h-[200px] flex-col items-center justify-center gap-4 rounded-2xl border border-red-900/40 bg-red-950/10 p-8 text-center">
          <div className="text-2xl">⚠</div>
          <div>
            <p className="text-sm font-medium text-red-300">화면 렌더링 오류</p>
            <p className="mt-1 max-w-sm text-xs text-slate-500">{this.state.error}</p>
          </div>
          <button
            onClick={this.reset}
            className="rounded-lg border border-slate-700 bg-slate-800 px-4 py-2 text-xs text-slate-300 hover:bg-slate-700"
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
