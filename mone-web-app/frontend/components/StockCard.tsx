'use client';

import { useEffect, useState } from 'react';
import { AlertTriangle, Ban, Shield, TrendingDown, TrendingUp } from 'lucide-react';
import type { StockCandidate } from '@/lib/types';
import { changeColor, fmtPct, fmtPrice, stockLabel } from '@/lib/utils';
import StatusBadge from './ui/StatusBadge';

interface Props {
  stock: StockCandidate;
  onClick?: () => void;
}

const modeColor: Record<string, string> = {
  보수: 'text-sky-400 bg-sky-400/10 border-sky-400/30',
  conservative: 'text-sky-400 bg-sky-400/10 border-sky-400/30',
  균형: 'text-violet-400 bg-violet-400/10 border-violet-400/30',
  balanced: 'text-violet-400 bg-violet-400/10 border-violet-400/30',
  공격: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
  aggressive: 'text-orange-400 bg-orange-400/10 border-orange-400/30',
};

const periodColor: Record<string, string> = {
  단기: 'text-emerald-400',
  short: 'text-emerald-400',
  스윙: 'text-blue-400',
  swing: 'text-blue-400',
  중기: 'text-purple-400',
  mid: 'text-purple-400',
  long: 'text-purple-400',
};

const modeWeight: Record<string, number> = {
  보수: 0.02,
  conservative: 0.02,
  균형: 0.05,
  balanced: 0.05,
  공격: 0.12,
  aggressive: 0.12,
};

const CASH_KEY = 'mone_cash_amount';

function useMoneCash() {
  const [cash, setCash] = useState(0);

  useEffect(() => {
    const read = () => setCash(Number(window.localStorage.getItem(CASH_KEY) || '0'));
    read();
    window.addEventListener('mone-cash-updated', read as EventListener);
    window.addEventListener('storage', read);
    return () => {
      window.removeEventListener('mone-cash-updated', read as EventListener);
      window.removeEventListener('storage', read);
    };
  }, []);

  return cash;
}

function modeLabel(value: string) {
  if (value === 'conservative') return '보수';
  if (value === 'balanced') return '균형';
  if (value === 'aggressive') return '공격';
  return value;
}

function periodLabel(value: string) {
  if (value === 'short') return '단기';
  if (value === 'swing') return '스윙';
  if (value === 'mid' || value === 'long') return '중기';
  return value;
}

export default function StockCard({ stock, onClick }: Props) {
  const isBanned = Boolean(stock.isBanned);
  const cash = useMoneCash();
  const allocation = cash * (modeWeight[String(stock.mode)] ?? 0.05);
  const orderQty = stock.entryPrice && stock.entryPrice > 0 ? Math.floor(allocation / stock.entryPrice) : 0;

  return (
    <div
      className={`card p-4 cursor-pointer animate-slide-up transition-all ${
        isBanned ? 'opacity-60' : 'hover:border-blue-500/40 hover:shadow-glow'
      }`}
      onClick={onClick}
    >
      <div className="flex items-start justify-between mb-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="font-semibold text-sm text-white">
              {stockLabel(stock.symbol, stock.name, stock.market)}
            </span>
            {isBanned && <Ban size={12} className="text-red-400" />}
            <span className="text-[10px] text-slate-500 bg-slate-800 rounded px-1.5 py-0.5">
              {String(stock.market).toUpperCase()}
            </span>
          </div>
          <div className="flex items-center gap-2 mt-1">
            <span className={`text-[11px] border rounded px-1.5 py-0.5 font-medium ${modeColor[String(stock.mode)] ?? modeColor.balanced}`}>
              {modeLabel(String(stock.mode))}
            </span>
            <span className={`text-[11px] font-medium ${periodColor[String(stock.period)] ?? 'text-slate-400'}`}>
              {periodLabel(String(stock.period))}
            </span>
            {stock.sector && <span className="text-[11px] text-slate-500">{stock.sector}</span>}
          </div>
        </div>
        <div className="flex flex-col items-end gap-1">
          <StatusBadge status={stock.dataStatus} size="xs" />
          {stock.change !== null && (
            <div className={`flex items-center gap-1 text-sm font-mono font-semibold ${changeColor(stock.change)}`}>
              {stock.change > 0 ? <TrendingUp size={13} /> : stock.change < 0 ? <TrendingDown size={13} /> : null}
              {fmtPct(stock.change)}
            </div>
          )}
        </div>
      </div>

      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mb-3 text-xs">
        <PriceCell label="현재가" value={fmtPrice(stock.currentPrice, stock.market)} />
        <PriceCell label="기준가" value={fmtPrice(stock.entryPrice, stock.market)} tone="text-blue-300" />
        <PriceCell label="손절가" value={fmtPrice(stock.stopLoss, stock.market)} tone="text-red-400" />
        <PriceCell label="목표가" value={fmtPrice(stock.targetPrice, stock.market)} tone="text-emerald-400" />
      </div>

      {cash > 0 && orderQty > 0 && (
        <div className="mb-3 rounded-lg border border-blue-500/20 bg-blue-500/10 px-3 py-2 text-xs">
          <div className="flex items-center justify-between gap-3">
            <span className="text-slate-300">추천 수량</span>
            <span className="font-mono font-bold text-blue-200">{orderQty.toLocaleString()}주</span>
          </div>
          <div className="mt-1 text-[10px] text-slate-500">
            예수금 {cash.toLocaleString()}원 기준 · {modeLabel(String(stock.mode))} 성향 배분액 {Math.floor(allocation).toLocaleString()}원
          </div>
        </div>
      )}

      <div className="flex items-center gap-3 mb-3">
        <Metric label="손익비" value={stock.rrRatio ? `1:${stock.rrRatio.toFixed(1)}` : '-'} good={Boolean(stock.rrRatio && stock.rrRatio >= 2)} />
        <Metric label="단기 확률" value={stock.probShort ? `${stock.probShort}%` : '-'} good={Boolean((stock.probShort ?? 0) >= 60)} />
        <Metric label="예상가" value={fmtPrice(stock.expectedPrice, stock.market)} />
      </div>

      {stock.warnings.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {stock.warnings.map((warning, index) => (
            <span key={`${warning}-${index}`} className="inline-flex items-center gap-1 text-[10px] text-amber-400 bg-amber-400/10 border border-amber-400/20 rounded px-1.5 py-0.5">
              <AlertTriangle size={9} />
              {warning}
            </span>
          ))}
        </div>
      )}

      {isBanned && stock.banReason && (
        <div className="mt-2 flex items-center gap-1.5 text-xs text-red-400 bg-red-400/10 border border-red-400/20 rounded px-2 py-1.5">
          <Shield size={11} />
          매수금지: {stock.banReason}
        </div>
      )}
    </div>
  );
}

function PriceCell({ label, value, tone = 'text-white' }: { label: string; value: string; tone?: string }) {
  return (
    <div>
      <div className="text-slate-500 mb-0.5">{label}</div>
      <div className={`font-mono font-semibold text-sm ${tone}`}>{value}</div>
    </div>
  );
}

function Metric({ label, value, good }: { label: string; value: string; good?: boolean }) {
  const color = good === undefined ? 'text-slate-300' : good ? 'text-emerald-400' : 'text-amber-400';
  return (
    <div className="flex-1 bg-slate-800/80 rounded-lg p-2.5 text-center">
      <div className="text-[10px] text-slate-500 mb-0.5">{label}</div>
      <div className={`font-mono font-bold text-sm ${color}`}>{value}</div>
    </div>
  );
}
