'use client';
import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

export default function SeasonsPage() {
  const [items, setItems] = useState<any[]>([]);
  const [form, setForm] = useState<any>({ name: '', start_date: '', end_date: '', is_active: true });
  const [id, setId] = useState('');
  const load = async () => {
    const d: any = await apiFetch('/seasons?page_size=200', {}, getToken());
    setItems(d.items || []);
  };
  useEffect(() => {
    load();
  }, []);
  const save = async () => {
    if (id) await apiFetch(`/seasons/${id}`, { method: 'PUT', body: JSON.stringify(form) }, getToken());
    else await apiFetch('/seasons', { method: 'POST', body: JSON.stringify(form) }, getToken());
    setForm({ name: '', start_date: '', end_date: '', is_active: true });
    setId('');
    await load();
  };
  const publish = async (seasonId: string) => {
    if (!window.confirm('Publishing will make this schedule visible to coaches, communities, parents, and field operators.')) return;
    await apiFetch(`/seasons/${seasonId}/publish-schedule`, { method: 'POST' }, getToken());
    await load();
  };
  const unpublish = async (seasonId: string) => {
    await apiFetch(`/seasons/${seasonId}/unpublish-schedule`, { method: 'POST' }, getToken());
    await load();
  };

  return <div className='space-y-4'><h1 className='text-2xl font-bold'>Seasons</h1><div className='grid gap-2 md:grid-cols-5'><input className='rounded border p-2' placeholder='Name' value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/><input className='rounded border p-2' type='date' value={form.start_date} onChange={e=>setForm({...form,start_date:e.target.value})}/><input className='rounded border p-2' type='date' value={form.end_date} onChange={e=>setForm({...form,end_date:e.target.value})}/><label className='flex items-center gap-2'><input type='checkbox' checked={form.is_active} onChange={e=>setForm({...form,is_active:e.target.checked})}/>Active</label><button className='rounded bg-emerald-700 px-3 py-2 text-white' onClick={save}>{id?'Update':'Create'}</button></div><table className='w-full text-sm'><thead><tr><th>Name</th><th>Status</th><th>Actions</th></tr></thead><tbody>{items.map((x:any)=><tr key={x.id}><td>{x.name}</td><td className='capitalize'>{x.schedule_status || 'draft'}</td><td className='space-x-2'><button className='underline' onClick={()=>{setId(x.id);setForm({...x});}}>Edit</button>{x.schedule_status === 'published' ? <button className='underline' onClick={()=>unpublish(x.id)}>Unpublish Schedule</button> : <button className='underline' onClick={()=>publish(x.id)}>Publish Schedule</button>}</td></tr>)}</tbody></table></div>;
}
