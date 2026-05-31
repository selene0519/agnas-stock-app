'use client';
import { LineChart, Line, ResponsiveContainer, Tooltip } from 'recharts';

interface Props {
  data: number[];
  color?: string;
  height?: number;
}

export default function MiniChart({ data, color = '#3b82f6', height = 40 }: Props) {
  const chartData = data.map((v, i) => ({ i, v }));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={chartData} margin={{ top: 2, right: 2, bottom: 2, left: 2 }}>
        <Line type="monotone" dataKey="v" stroke={color} strokeWidth={1.5} dot={false} />
        <Tooltip
          content={({ active, payload }) =>
            active && payload?.length ? (
              <div className="text-xs bg-slate-800 border border-slate-600 rounded px-2 py-1" style={{ color }}>
                {payload[0].value?.toLocaleString()}
              </div>
            ) : null
          }
        />
      </LineChart>
    </ResponsiveContainer>
  );
}

