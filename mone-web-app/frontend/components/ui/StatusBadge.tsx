'use client';
import { statusClass, statusLabel } from '@/lib/utils';
import type { DataStatus } from '@/lib/types';

export default function StatusBadge({ status, size = 'sm' }: { status: DataStatus; size?: 'xs' | 'sm' }) {
  const px = size === 'xs' ? 'px-1.5 py-0.5 text-[10px]' : 'px-2 py-0.5 text-xs';
  return (
    <span className={`${statusClass(status)} ${px} rounded font-mono font-semibold tracking-wide inline-flex items-center gap-1`}>
      {status === 'NORMAL' && <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse-dot inline-block" />}
      {status === 'STALE' && <span className="w-1.5 h-1.5 rounded-full bg-red-400 inline-block" />}
      {status === 'PARTIAL' && <span className="w-1.5 h-1.5 rounded-full bg-amber-400 inline-block" />}
      {statusLabel(status)}
    </span>
  );
}

