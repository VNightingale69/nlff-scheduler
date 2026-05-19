'use client';

type Props = { items: any[]; columns: string[]; onEdit: (item: any) => void; onDelete: (item: any) => void };

export default function DataTable({ items, columns, onEdit, onDelete }: Props) {
  return <div className='overflow-x-auto rounded border'><table className='w-full text-left text-sm'><thead className='bg-slate-100'><tr>{columns.map((c) => <th key={c} className='px-3 py-2'>{c}</th>)}<th className='px-3 py-2'>Actions</th></tr></thead><tbody>{items.map((item) => <tr key={item.id} className='border-t'>{columns.map((c) => <td key={c} className='px-3 py-2'>{typeof item[c] === 'boolean' ? (item[c] ? 'Active' : 'Inactive') : String(item[c] ?? '-')}</td>)}<td className='space-x-2 px-3 py-2'><button className='text-blue-700' onClick={() => onEdit(item)}>Edit</button><button className='text-rose-700' onClick={() => onDelete(item)}>Delete</button></td></tr>)}</tbody></table></div>;
}
