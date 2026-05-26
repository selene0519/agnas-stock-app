import type { ReactNode } from "react";

export type Column<T> = {
  key: string;
  header: string;
  render: (row: T) => ReactNode;
};

export function DataTable<T>({
  rows,
  columns,
  onRowClick
}: {
  rows: T[];
  columns: Column<T>[];
  onRowClick?: (row: T) => void;
}) {
  return (
    <div className="overflow-hidden rounded-lg border border-line bg-panel">
      <div className="scrollbar-thin overflow-x-auto">
        <table
          className="w-full border-collapse text-sm"
          style={{ minWidth: columns.length <= 6 ? "100%" : `${Math.max(900, columns.length * 128)}px` }}
        >
          <thead className="bg-white/[0.03] text-xs uppercase tracking-wide text-muted">
            <tr>
              {columns.map((col) => (
                <th key={col.key} className="whitespace-nowrap border-b border-line px-3 py-2 text-left font-bold">
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, idx) => (
              <tr
                key={idx}
                onClick={() => onRowClick?.(row)}
                className={onRowClick ? "cursor-pointer hover:bg-accent/10" : "hover:bg-white/[0.025]"}
              >
                {columns.map((col) => (
                  <td key={col.key} className="whitespace-nowrap border-b border-line px-3 py-2 align-top text-slate-200">
                    {col.render(row)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
