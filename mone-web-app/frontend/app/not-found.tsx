import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex min-h-screen flex-col items-center justify-center gap-6 bg-slate-950 text-slate-100">
      <div className="text-center">
        <p className="text-6xl font-bold text-slate-700">404</p>
        <h1 className="mt-3 text-xl font-semibold">페이지를 찾을 수 없습니다</h1>
        <p className="mt-2 text-sm text-slate-500">요청한 페이지가 존재하지 않거나 이동되었습니다.</p>
      </div>
      <Link
        href="/"
        className="rounded-xl bg-blue-600 px-6 py-2.5 text-sm font-medium text-white hover:bg-blue-500"
      >
        홈으로 돌아가기
      </Link>
    </div>
  );
}
