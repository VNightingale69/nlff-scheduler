'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import Toast from './Toast';

const HOSTING_DATES = [
  { date: '2026-09-06', label: 'Saturday, September 6', type: 'regular' },
  { date: '2026-09-13', label: 'Saturday, September 13', type: 'regular' },
  { date: '2026-09-20', label: 'Saturday, September 20', type: 'regular' },
  { date: '2026-09-27', label: 'Saturday, September 27', type: 'regular' },
  { date: '2026-10-04', label: 'Saturday, October 4', type: 'regular' },
  { date: '2026-10-11', label: 'Saturday, October 11', type: 'regular' },
  { date: '2026-10-18', label: 'Saturday, October 18 — Playoffs', type: 'playoffs' },
  { date: '2026-10-25', label: 'Saturday, October 25 — Championships', type: 'championships' },
] as const;

const HOURS = [9,10,11,12,13,14,15,16];
const slotKey = (fieldId:string,date:string,hour:number)=>`${fieldId}|${date}|${hour}`;

export default function HostingAvailabilityManager(){
  const [message,setMessage]=useState(''); const [type,setType]=useState<'ok'|'err'>('ok');
  const [orgs,setOrgs]=useState<any[]>([]); const [hosts,setHosts]=useState<any[]>([]); const [fields,setFields]=useState<any[]>([]);
  const [selectedDates,setSelectedDates]=useState<string[]>([]); const [orgId,setOrgId]=useState(''); const [hostId,setHostId]=useState('');
  const [selectedSlots,setSelectedSlots]=useState<Record<string,boolean>>({});
  const [loading,setLoading]=useState(true); const [saving,setSaving]=useState(false);
  const user = getAuthUser(); const token = getToken();

  useEffect(()=>{(async()=>{setLoading(true); try{ const [o,h,f]=await Promise.all([apiFetch('/organizations?page_size=500',{},token),apiFetch('/host-locations?page_size=500',{},token),apiFetch('/fields?page_size=500',{},token)]); setOrgs(o.items||[]); setHosts(h.items||[]); setFields(f.items||[]); if(user?.role_name==='community_scheduler'){ setOrgId(user.organization_id || ''); }}catch(e:any){setMessage(e.message||'Failed to load');setType('err');} finally{setLoading(false);} })();},[]);

  const hostOptions = useMemo(()=>hosts.filter((h:any)=>!orgId || h.organization_id===orgId),[hosts,orgId]);
  const visibleFields = useMemo(()=>fields.filter((f:any)=>!hostId || f.host_location_id===hostId),[fields,hostId]);

  useEffect(()=>{ if(!hostOptions.some((h:any)=>h.id===hostId)) setHostId(''); },[hostOptions,hostId]);

  useEffect(()=>{(async()=>{ if(!selectedDates.length || !visibleFields.length) return; const params=new URLSearchParams(); params.set('page_size','2000'); params.set('field_ids', visibleFields.map((f:any)=>f.id).join(',')); params.set('available_dates', selectedDates.join(',')); try{ const data=await apiFetch(`/hosting-availabilities?${params.toString()}`,{},token); const map:Record<string,boolean>={}; for(const item of (data.items||[])){ const hr=Number(String(item.start_time).slice(0,2)); map[slotKey(item.field_id,item.available_date,hr)] = item.is_available; } setSelectedSlots((prev)=>({...prev,...map})); }catch{} })();},[selectedDates.join(','),visibleFields.map((f:any)=>f.id).join(',')]);

  const toggleHour=(fieldId:string,date:string,hour:number)=>setSelectedSlots((p)=>({ ...p, [slotKey(fieldId,date,hour)]: !p[slotKey(fieldId,date,hour)] }));
  const allDay=(fieldId:string,date:string)=>HOURS.every((h)=>selectedSlots[slotKey(fieldId,date,h)]);
  const toggleAllDay=(fieldId:string,date:string,on:boolean)=>setSelectedSlots((p)=>{const n={...p}; for(const h of HOURS){n[slotKey(fieldId,date,h)] = on;} return n;});

  const save=async()=>{ if(!selectedDates.length || !visibleFields.length){setMessage('Select dates and a host location first.');setType('err');return;} setSaving(true); try{ const slots:any[]=[]; for(const field of visibleFields){ for(const d of selectedDates){ for(const h of HOURS){ if(selectedSlots[slotKey(field.id,d,h)]) slots.push({field_id:field.id,available_date:d,start_time:`${String(h).padStart(2,'0')}:00:00`,end_time:`${String(h+1).padStart(2,'0')}:00:00`,is_available:true}); } } } await apiFetch('/hosting-availabilities/bulk-upsert',{method:'POST',body:JSON.stringify({slots})},token); setMessage('Availability saved successfully.'); setType('ok'); }catch(e:any){ setMessage(e.message||'Save failed'); setType('err'); } finally{setSaving(false);} };

  return <div className='space-y-4'>
    <Toast message={message} type={type}/><h1 className='text-2xl font-bold'>Hosting Availability</h1>
    <section className='rounded border p-4'><h2 className='mb-2 font-semibold'>1. Select Hosting Dates</h2><div className='grid gap-2 md:grid-cols-2 lg:grid-cols-4'>{HOSTING_DATES.map(d=><button key={d.date} onClick={()=>setSelectedDates((p)=>p.includes(d.date)?p.filter(x=>x!==d.date):[...p,d.date])} className={`rounded border p-3 text-left ${selectedDates.includes(d.date)?'border-emerald-600 bg-emerald-50':''}`}><div className='text-sm'>{d.label}</div><div className='mt-1 text-xs uppercase text-slate-500'>{d.type}</div></button>)}</div></section>
    <section className='rounded border p-4'><h2 className='mb-2 font-semibold'>2. Select Organization / Host Location</h2><div className='grid gap-2 md:grid-cols-2'><select disabled={user?.role_name==='community_scheduler'} value={orgId} onChange={(e)=>setOrgId(e.target.value)} className='rounded border p-2'><option value=''>Select organization</option>{orgs.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select><select value={hostId} onChange={(e)=>setHostId(e.target.value)} className='rounded border p-2'><option value=''>Select host location</option>{hostOptions.map((h:any)=><option key={h.id} value={h.id}>{h.name}</option>)}</select></div></section>
    <section className='rounded border p-4 overflow-auto'><h2 className='mb-2 font-semibold'>3. Field Availability Grid</h2>{loading ? <p>Loading...</p> : selectedDates.length===0 || !hostId ? <p className='text-slate-500'>Select at least one date and host location to begin.</p> : <div className='space-y-4'>{selectedDates.map((date)=><div key={date} className='space-y-2'><h3 className='font-medium'>{HOSTING_DATES.find((d)=>d.date===date)?.label || date}</h3><table className='w-full border-collapse text-xs'><thead><tr><th className='border p-2 text-left'>Field</th><th className='border p-2'>All Day</th>{HOURS.map((h)=><th key={h} className='border p-2'>{h<=11?`${h}:00 AM` : h===12?'12:00 PM':`${h-12}:00 PM`}</th>)}</tr></thead><tbody>{visibleFields.map((f:any)=>{const host=hosts.find((h:any)=>h.id===f.host_location_id); return <tr key={`${f.id}-${date}`}><td className='border p-2'>{f.name}<div className='text-[11px] text-slate-500'>{f.layout_type} • {host?.name}</div></td><td className='border p-2 text-center'><input type='checkbox' checked={allDay(f.id,date)} onChange={(e)=>toggleAllDay(f.id,date,e.target.checked)} /></td>{HOURS.map((h)=><td key={h} className='border p-2 text-center'><button className={`h-6 w-10 rounded border ${selectedSlots[slotKey(f.id,date,h)]?'bg-emerald-600 text-white':'bg-white'}`} onClick={()=>toggleHour(f.id,date,h)}>{selectedSlots[slotKey(f.id,date,h)]?'✓':''}</button></td>)}</tr>;})}</tbody></table></div>)}</div>}</section>
    <div className='flex gap-2'><button className='rounded bg-emerald-700 px-4 py-2 text-white disabled:opacity-50' onClick={save} disabled={saving}>{saving?'Saving…':'Save Availability'}</button><button className='rounded border px-4 py-2' onClick={()=>setSelectedSlots({})}>Cancel/Reset</button></div>
  </div>;
}
