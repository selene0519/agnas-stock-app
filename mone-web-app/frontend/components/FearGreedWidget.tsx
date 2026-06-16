"use client";

import { useEffect, useState } from "react";
import { mone } from "@/lib/api";

type FgData = {
  status?: string;
  score: number;
  label: string;
  color: string;
  source: string;
  history?: Array<{ date: string; score: number }>;
  components?: Array<{ name: string; score: number; direction: string }>;
  kr?: { score: number; label: string; color: string; source: string };
  us?: { score: number; label: string; color: string; source: string };
  composite?: { score: number; label: string; color: string };
};

// 반원 게이지 SVG
function GaugeArc({ score, color }: { score: number; color: string }) {
  const R = 48;
  const cx = 60;
  const cy = 60;
  // 반원: 180° ~ 0° (왼쪽→오른쪽)
  const angle = 180 - (score / 100) * 180; // degrees from left
  const rad = (angle * Math.PI) / 180;
  const nx = cx + R * Math.cos(rad);
  const ny = cy - R * Math.sin(rad);

  // 배경 반원 path
  const bgPath = `M ${cx - R} ${cy} A ${R} ${R} 0 0 1 ${cx + R} ${cy}`;
  // 채움 호 (score에 따라)
  const fillAngle = (score / 100) * 180;
  const largeArc = fillAngle > 180 ? 1 : 0;
  const fillEndRad = ((180 - fillAngle) * Math.PI) / 180;
  const fex = cx + R * Math.cos(fillEndRad);
  const fey = cy - R * Math.sin(fillEndRad);
  const fillPath = `M ${cx - R} ${cy} A ${R} ${R} 0 ${largeArc} 1 ${fex} ${fey}`;

  return (
    <svg viewBox="0 0 120 70" className="w-full max-w-[160px]">
      {/* 배경 반원 */}
      <path d={bgPath} fill="none" stroke="#1e293b" strokeWidth="10" strokeLinecap="round" />
      {/* 채움 호 */}
      {score > 0 && (
        <path
          d={fillPath}
          fill="none"
          stroke={color}
          strokeWidth="10"
          strokeLinecap="round"
          opacity="0.9"
        />
      )}
      {/* 바늘 */}
      <line
        x1={cx}
        y1={cy}
        x2={nx}
        y2={ny}
        stroke={color}
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx={cx} cy={cy} r="3.5" fill={color} />
      {/* 점수 */}
      <text
        x={cx}
        y={cy + 14}
        textAnchor="middle"
        fontSize="14"
        fontWeight="bold"
        fill="white"
        fontFamily="monospace"
      >
        {Math.round(score)}
      </text>
    </svg>
  );
}

function MiniBar({ history }: { history: Array<{ date: string; score: number }> }) {
  if (!history || history.length < 2) return null;
  const max = 100;
  const w = 100 / history.length;
  return (
    <div className="flex items-end gap-0.5 h-6" title="7일 추이">
      {history.map((h, i) => {
        const pct = (h.score / max) * 100;
        const col =
          h.score < 20 ? "bg-red-500" :
          h.score < 40 ? "bg-orange-400" :
          h.score < 60 ? "bg-yellow-400" :
          h.score < 80 ? "bg-lime-400" : "bg-green-400";
        return (
          <div
            key={i}
            className={`flex-1 rounded-sm ${col} opacity-70`}
            style={{ height: `${Math.max(15, pct)}%` }}
            title={`${h.date}: ${h.score}`}
          />
        );
      })}
    </div>
  );
}

function FgCard({
  label,
  data,
  size = "sm",
}: {
  label: string;
  data: { score: number; label: string; color: string; source: string; history?: Array<{ date: string; score: number }> } | undefined;
  size?: "sm" | "lg";
}) {
  if (!data) return null;
  return (
    <div className="flex flex-col items-center gap-1">
      <span className="text-[10px] font-bold uppercase tracking-wider text-slate-500">{label}</span>
      <GaugeArc score={data.score} color={data.color} />
      <span
        className="text-xs font-bold"
        style={{ color: data.color }}
      >
        {data.label}
      </span>
      {data.history && <MiniBar history={data.history} />}
      <span className="text-[9px] text-slate-600 text-center leading-tight max-w-[120px]">{data.source}</span>
    </div>
  );
}

export default function FearGreedWidget({ market = "all" }: { market?: string }) {
  const [data, setData] = useState<FgData | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    mone
      .fearGreed({ market })
      .then((res: any) => {
        if (!cancelled) setData(res as FgData);
      })
      .catch(() => {
        if (!cancelled) setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => { cancelled = true; };
  }, [market]);

  if (loading) {
    return (
      <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 px-4 py-3 text-center text-[11px] text-slate-500 animate-pulse">
        공포탐욕지수 로딩 중...
      </div>
    );
  }
  if (!data || data.status === "ERROR") return null;

  const showBoth = market === "all" && data.kr && data.us;

  return (
    <div className="rounded-2xl border border-slate-700/60 bg-slate-900/50 px-4 py-3">
      <div className="flex items-center justify-between mb-3">
        <p className="text-[10px] font-bold uppercase tracking-widest text-slate-500">공포·탐욕 지수</p>
        {data.composite && (
          <span
            className="text-[11px] font-bold"
            style={{ color: data.composite.color }}
          >
            종합 {Math.round(data.composite.score)} · {data.composite.label}
          </span>
        )}
      </div>

      {showBoth ? (
        <div className="grid grid-cols-2 gap-4">
          <FgCard label="국장 (KOSPI)" data={data.kr} />
          <FgCard label="미장 (CNN/SPY)" data={data.us} />
        </div>
      ) : (
        <div className="flex justify-center">
          <FgCard
            label={market === "kr" ? "국장 (KOSPI)" : "미장 (CNN/SPY)"}
            data={data as any}
          />
        </div>
      )}

      {/* 컴포넌트 상세 (단일 마켓) */}
      {!showBoth && Array.isArray(data.components) && data.components.length > 0 && (
        <div className="mt-3 space-y-1.5 border-t border-slate-700/40 pt-3">
          {data.components.map((c, i) => (
            <div key={i} className="flex items-center justify-between text-[11px]">
              <span className="text-slate-400">{c.name}</span>
              <div className="flex items-center gap-2">
                <span className="text-slate-500 font-mono">{c.direction}</span>
                <div className="w-16 h-1.5 rounded-full bg-slate-800">
                  <div
                    className="h-full rounded-full"
                    style={{
                      width: `${c.score}%`,
                      backgroundColor:
                        c.score < 40 ? "#f97316" : c.score < 60 ? "#eab308" : "#84cc16",
                    }}
                  />
                </div>
                <span className="w-8 text-right font-mono text-slate-300">{c.score}</span>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
