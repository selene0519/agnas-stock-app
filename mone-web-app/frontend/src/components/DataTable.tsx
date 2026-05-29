import type { ReactNode } from "react";

export type Column<T = any> = {
  key?: keyof T | string;
  header?: ReactNode;
  label?: ReactNode;
  title?: ReactNode;
  accessor?: keyof T | string | ((row: T) => ReactNode);
  render?: (row: T, index: number) => ReactNode;
  className?: string;
  align?: "left" | "center" | "right";
  width?: string | number;
};

type DataTableProps<T = any> = {
  columns: Column<T>[];
  rows?: T[];
  data?: T[];
  items?: T[];
  emptyText?: ReactNode;
  rowKey?: keyof T | string | ((row: T, index: number) => string | number);
  onRowClick?: (row: T) => void;
  className?: string;
};

function readValue<T>(row: T, key?: keyof T | string) {
  if (!key) return "";
  return (row as any)?.[key as string] ?? "";
}

export function DataTable<T = any>({
  columns,
  rows,
  data,
  items,
  emptyText = "표시할 데이터가 없습니다.",
  rowKey,
  onRowClick,
  className = "",
}: DataTableProps<T>) {
  const list = rows ?? data ?? items ?? [];

  const getKey = (row: T, index: number) => {
    if (typeof rowKey === "function") return rowKey(row, index);
    if (rowKey) return String((row as any)?.[rowKey as string] ?? index);
    return index;
  };

  if (!list.length) {
    return (
      <div className="rounded-2xl border border-slate-800 bg-slate-950/60 p-5 text-sm text-slate-400">
        {emptyText}
      </div>
    );
  }

  return (
    <div className={`overflow-x-auto rounded-2xl border border-slate-800 ${className}`}>
      <table className="min-w-full border-collapse text-sm">
        <thead className="bg-slate-900 text-slate-300">
          <tr>
            {columns.map((col, idx) => (
              <th
                key={String(col.key ?? idx)}
                className={`border-b border-slate-800 px-4 py-3 text-${col.align ?? "left"} font-black`}
                style={{ width: col.width }}
              >
                {col.header ?? col.label ?? col.title ?? String(col.key ?? "")}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {list.map((row, rowIndex) => (
            <tr
              key={getKey(row, rowIndex)}
              onClick={() => onRowClick?.(row)}
              className={`border-b border-slate-900/80 ${onRowClick ? "cursor-pointer hover:bg-slate-900/60" : ""}`}
            >
              {columns.map((col, colIndex) => {
                const value =
                  col.render?.(row, rowIndex) ??
                  (typeof col.accessor === "function"
                    ? col.accessor(row)
                    : readValue(row, (col.accessor as string) ?? (col.key as string)));

                return (
                  <td
                    key={String(col.key ?? colIndex)}
                    className={`px-4 py-3 text-${col.align ?? "left"} text-slate-100 ${col.className ?? ""}`}
                  >
                    {value as ReactNode}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
