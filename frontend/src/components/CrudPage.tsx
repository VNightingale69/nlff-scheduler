'use client';
import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';
import Toast from './Toast';
import FormField from './ui/FormField';
import DataTable from './ui/DataTable';

export default function CrudPage({ title, path, fields }: { title: string; path: string; fields: { key: string; label: string; type?: string }[] }) {
  const [items, setItems] = useState<any[]>([]);
  const [query, setQuery] = useState('');
  const [form, setForm] = useState<any>({});
  const [editingId, setEditingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [message, setMessage] = useState('');
  const [type, setType] = useState<'ok' | 'err'>('ok');

  const load = async () => {
    setLoading(true);
    try {
      const d = await apiFetch(`${path}?search=${encodeURIComponent(query)}`, {}, getToken());
      setItems(d.items || []);
    } catch {
      setMessage('Failed to load records'); setType('err');
    } finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const missingRequired = useMemo(
    () =>
      fields
        .filter((f) => f.type !== 'checkbox')
        .filter((f) => {
          const value = form[f.key];
          if (value === undefined || value === null) return true;
          if (typeof value === 'string') return value.trim().length === 0;
          if (f.type === 'number') return Number.isNaN(Number(value));
          return value === '';
        })
        .map((f) => f.label),
    [fields, form]
  );

  const save = async () => {
    if (missingRequired.length) { setMessage(`Missing: ${missingRequired.join(', ')}`); setType('err'); return; }
    setSaving(true);
    try {
      const payload = fields.reduce<Record<string, unknown>>((acc, field) => {
        const rawValue = form[field.key];
        if (field.type === 'number') acc[field.key] = Number(rawValue);
        else if (field.type === 'text' || !field.type) acc[field.key] = typeof rawValue === 'string' ? rawValue.trim() : rawValue;
        else acc[field.key] = rawValue;
        return acc;
      }, {});

      if (editingId) await apiFetch(`${path}/${editingId}`, { method: 'PUT', body: JSON.stringify(payload) }, getToken());
      else await apiFetch(path, { method: 'POST', body: JSON.stringify(payload) }, getToken());
      setMessage(editingId ? 'Updated successfully' : 'Created successfully'); setType('ok'); setForm({}); setEditingId(null); load();
    } catch (e: any) { setMessage(e?.message || 'Save failed'); setType('err'); }
    finally { setSaving(false); }
  };

  const edit = (item: any) => { setForm(item); setEditingId(item.id); };
  const del = async (item: any) => {
    if (!confirm(`Delete ${item.name || item.id}?`)) return;
    try { await apiFetch(`${path}/${item.id}`, { method: 'DELETE' }, getToken()); setMessage('Deleted successfully'); setType('ok'); load(); }
    catch { setMessage('Delete failed'); setType('err'); }
  };

  return <div className='space-y-4'><Toast message={message} type={type} /><h1 className='text-2xl font-bold'>{title}</h1><div className='flex gap-2'><input className='w-full max-w-sm rounded border p-2' value={query} onChange={(e) => setQuery(e.target.value)} placeholder='Search...' /><button className='rounded bg-slate-700 px-3 py-2 text-white' onClick={load}>Filter</button></div><div className='grid gap-3 rounded border p-4 md:grid-cols-2'>{fields.map((f) => <FormField key={f.key} label={f.label} type={f.type} value={form[f.key] ?? (f.type === 'checkbox' ? true : '')} onChange={(value) => setForm({ ...form, [f.key]: value })} />)}<div className='md:col-span-2 flex gap-2'><button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:cursor-not-allowed disabled:opacity-50' onClick={save} disabled={saving}>{saving ? 'Saving…' : editingId ? 'Update' : 'Create'}</button>{editingId && <button className='rounded border px-4 py-2 disabled:cursor-not-allowed disabled:opacity-50' onClick={() => { setForm({}); setEditingId(null); }} disabled={saving}>Cancel</button>}</div></div>{loading ? <p>Loading records...</p> : items.length === 0 ? <div className='rounded border border-dashed p-6 text-center text-slate-500'>No records yet.</div> : <DataTable items={items} columns={fields.map((f) => f.key)} onEdit={edit} onDelete={del} />}</div>;
}
