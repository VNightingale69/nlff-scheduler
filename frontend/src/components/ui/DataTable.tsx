'use client';

import { formatDisplayDate, formatDisplayTime } from '@/lib/displayFormat';

type Props = { items: any[]; columns: string[]; onEdit: (item: any) => void; onDelete: (item: any) => void; valueLabels?: Record<string, Record<string, string>>; headerLabels?: Record<string, string> };

const formatTableValue = (column: string, value: unknown, valueLabels: Record<string, Record<string, string>>) => {
  if (typeof value === 'boolean') return value ? 'Active' : 'Inactive';

  const labeledValue = valueLabels[column]?.[String(value)];
  if (labeledValue) return labeledValue;

  if (value === undefined || value === null || value === '') return '-';

  if (column.endsWith('_date') || column === 'date') return formatDisplayDate(String(value));
  if (column.endsWith('_time') || column === 'time') return formatDisplayTime(String(value));

  return String(value);
};

export default function DataTable({ items, columns, onEdit, onDelete, valueLabels = {}, headerLabels = {} }: Props) {
  return <div className='overflow-x-auto rounded border'><table className='w-full text-left text-sm'><thead className='bg-slate-100'><tr>{columns.map((c) => <th key={c} className='px-3 py-2'>{headerLabels[c] ?? c}</th>)}<th className='px-3 py-2'>Actions</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className='border-t'>{columns.map((c) => <td key={c} className='px-3 py-2'>{formatTableValue(c, item[c], valueLabels)}</td>)}<td className='space-x-2 px-3 py-2'><button className='text-blue-700' onClick={() => onEdit(item)}>Edit</button><button className='text-rose-700' onClick={() => onDelete(item)}>Delete</button></td></tr>)}</tbody></table></div>;
}
