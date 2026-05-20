'use client';

import { useEffect, useMemo, useState } from 'react';
import { apiFetch } from '@/lib/api';
import { getAuthUser, getToken } from '@/lib/auth';
import Toast from './Toast';

const HOSTING_DATES = [
  { date: '2026-09-06', label: 'Saturday, September 6' },{ date: '2026-09-13', label: 'Saturday, September 13' },{ date: '2026-09-20', label: 'Saturday, September 20' },{ date: '2026-09-27', label: 'Saturday, September 27' },{ date: '2026-10-04', label: 'Saturday, October 4' },{ date: '2026-10-11', label: 'Saturday, October 11' },{ date: '2026-10-18', label: 'Saturday, October 18 — Playoffs' },{ date: '2026-10-25', label: 'Saturday, October 25 — Championships' },
] as const;
const HOURS = [9,10,11,12,13,14,15,16];
const slotKey = (areaId:string,configId:string,date:string,hour:number)=>`${areaId}|${configId}|${date}|${hour}`;

export default function HostingAvailabilityManager(){
  const [message,setMessage]=useState(''); const [type,setType]=useState<'ok'|'err'>('ok');
  const [orgs,setOrgs]=useState<any[]>([]); const [hosts,setHosts]=useState<any[]>([]); const [areas,setAreas]=useState<any[]>([]); const [configs,setConfigs]=useState<any[]>([]);
  const [selectedDates,setSelectedDates]=useState<string[]>([]); const [orgId,setOrgId]=useState(''); const [hostId,setHostId]=useState('');
  const [selectedSlots,setSelectedSlots]=useState<Record<string,boolean>>({}); const [activeConfigByArea,setActiveConfigByArea]=useState<Record<string,string>>({});
  const [loading,setLoading]=useState(true); const [saving,setSaving]=useState(false);
  const user=getAuthUser(); const token=getToken();

  useEffect(()=>{(async()=>{setLoading(true);try{const [o,h,a,c]=await Promise.all([apiFetch('/organizations?page_size=500',{},token),apiFetch('/host-locations?page_size=500',{},token),apiFetch('/physical-field-areas?page_size=1000',{},token),apiFetch('/field-configuration-options?page_size=2000',{},token)]); setOrgs(o.items||[]); setHosts(h.items||[]); setAreas(a.items||[]); setConfigs(c.items||[]); if(user?.role_name==='community_scheduler') setOrgId(user.organization_id||'');}catch(e:any){setMessage(e.message||'Failed to load');setType('err');}finally{setLoading(false);}})();},[]);

  const hostOptions = useMemo(()=>hosts.filter((h:any)=>!orgId||h.organization_id===orgId),[hosts,orgId]);
  const visibleAreas = useMemo(()=>areas.filter((a:any)=>!hostId||a.host_location_id===hostId),[areas,hostId]);
  const configsByArea = useMemo(()=>configs.reduce((m:any,c:any)=>((m[c.physical_field_area_id]=[...(m[c.physical_field_area_id]||[]),c]),m),{}),[configs]);
  useEffect(()=>{ if(!hostOptions.some((h:any)=>h.id===hostId)) setHostId(''); },[hostOptions,hostId]);

  const toggleHour=(a:string,c:string,d:string,h:number)=>setSelectedSlots((p)=>({...p,[slotKey(a,c,d,h)]:!p[slotKey(a,c,d,h)]}));
  const allDay=(a:string,c:string,d:string)=>HOURS.every((h)=>selectedSlots[slotKey(a,c,d,h)]);
  const toggleAllDay=(a:string,c:string,d:string,on:boolean)=>setSelectedSlots((p)=>{const n={...p}; for(const h of HOURS){n[slotKey(a,c,d,h)]=on;} return n;});

  const save=async()=>{ if(!selectedDates.length||!visibleAreas.length){setType('err');setMessage('Select dates and host location first.'); return;} setSaving(true); try{const slots:any[]=[]; for(const area of visibleAreas){ const configId=activeConfigByArea[area.id]; if(!configId) continue; for(const d of selectedDates){ for(const h of HOURS){ if(selectedSlots[slotKey(area.id,configId,d,h)]) slots.push({physical_field_area_id:area.id,field_configuration_option_id:configId,available_date:d,start_time:`${String(h).padStart(2,'0')}:00:00`,end_time:`${String(h+1).padStart(2,'0')}:00:00`,is_available:true}); } } } await apiFetch('/hosting-availabilities/bulk-upsert',{method:'POST',body:JSON.stringify({slots})},token); setType('ok');setMessage('Availability saved successfully.'); }catch(e:any){setType('err');setMessage(e.message||'Save failed');} finally{setSaving(false);} };

  return <div className='space-y-4'><Toast message={message} type={type}/><h1 className='text-2xl font-bold'>Hosting Availability</h1>
  <section className='rounded border p-4'><h2 className='mb-2 font-semibold'>1. Select Hosting Dates</h2><div className='grid gap-2 md:grid-cols-2 lg:grid-cols-4'>{HOSTING_DATES.map(d=><button key={d.date} onClick={()=>setSelectedDates((p)=>p.includes(d.date)?p.filter(x=>x!==d.date):[...p,d.date])} className={`rounded border p-3 text-left ${selectedDates.includes(d.date)?'border-emerald-600 bg-emerald-50':''}`}>{d.label}</button>)}</div></section>
  <section className='rounded border p-4'><h2 className='mb-2 font-semibold'>2. Select Organization / Host Location</h2><div className='grid gap-2 md:grid-cols-2'><select disabled={user?.role_name==='community_scheduler'} value={orgId} onChange={e=>setOrgId(e.target.value)} className='rounded border p-2'><option value=''>Select organization</option>{orgs.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select><select value={hostId} onChange={e=>setHostId(e.target.value)} className='rounded border p-2'><option value=''>Select host location</option>{hostOptions.map((h:any)=><option key={h.id} value={h.id}>{h.name}</option>)}</select></div></section>
  <section className='rounded border p-4 overflow-auto'><h2 className='mb-2 font-semibold'>3. Physical Field Area Availability</h2>{loading||!hostId||!selectedDates.length?<p className='text-slate-500'>Select host location and dates.</p>:selectedDates.map((date)=><div key={date} className='mb-4'><h3 className='mb-2 font-medium'>{HOSTING_DATES.find(x=>x.date===date)?.label||date}</h3><table className='w-full text-xs border-collapse'><thead><tr><th className='border p-2 text-left'>Field Area</th><th className='border p-2'>Configuration</th><th className='border p-2'>All Day</th>{HOURS.map((h)=><th key={h} className='border p-2'>{h<=11?`${h}:00 AM`:h===12?'12:00 PM':`${h-12}:00 PM`}</th>)}</tr></thead><tbody>{visibleAreas.map((area:any)=>{const cfgs=configsByArea[area.id]||[]; const cfg=activeConfigByArea[area.id]||cfgs[0]?.id||''; return <tr key={`${area.id}-${date}`}><td className='border p-2'>{area.name}<div className='text-[11px] text-slate-500'>{area.field_space_type}</div></td><td className='border p-2'><select className='rounded border p-1 w-full' value={cfg} onChange={e=>setActiveConfigByArea({...activeConfigByArea,[area.id]:e.target.value})}>{cfgs.map((c:any)=><option key={c.id} value={c.id}>{c.name} (30y:{c.thirty_yard_capacity} / 53y:{c.fifty_three_yard_capacity})</option>)}</select></td><td className='border p-2 text-center'><input type='checkbox' checked={cfg?allDay(area.id,cfg,date):false} onChange={(e)=>cfg&&toggleAllDay(area.id,cfg,date,e.target.checked)} /></td>{HOURS.map((h)=><td key={h} className='border p-2 text-center'><button disabled={!cfg} onClick={()=>cfg&&toggleHour(area.id,cfg,date,h)} className={`h-6 w-10 rounded border ${cfg&&selectedSlots[slotKey(area.id,cfg,date,h)]?'bg-emerald-600 text-white':'bg-white'}`}>{cfg&&selectedSlots[slotKey(area.id,cfg,date,h)]?'✓':''}</button></td>)}</tr>;})}</tbody></table></div>)}</section>
  <button className='rounded bg-emerald-700 px-4 py-2 text-white' disabled={saving} onClick={save}>{saving?'Saving…':'Save Availability'}</button></div>;
}
