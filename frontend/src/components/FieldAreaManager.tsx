'use client';
import { useEffect, useMemo, useState } from 'react';
import Toast from './Toast';
import { apiFetch } from '@/lib/api';
import { getToken } from '@/lib/auth';

const STADIUM_TYPE = 'STADIUM_FIELD';
const GRASS_TYPE = 'GRASS_PARK_FIELDS';
const STADIUM_OPTIONS = [
  { name: '2x53', label: '2 x 53-yard fields', thirty: 0, fiftyThree: 2 },
  { name: '1x53_plus_2x30', label: '1 x 53-yard field + 2 x 30-yard fields', thirty: 2, fiftyThree: 1 },
  { name: '3x30', label: '3 x 30-yard fields', thirty: 3, fiftyThree: 0 },
];

export default function FieldAreaManager(){
  const token = getToken();
  const [message,setMessage]=useState(''); const [type,setType]=useState<'ok'|'err'>('ok');
  const [orgs,setOrgs]=useState<any[]>([]); const [hosts,setHosts]=useState<any[]>([]); const [areas,setAreas]=useState<any[]>([]); const [configs,setConfigs]=useState<any[]>([]);
  const [orgId,setOrgId]=useState('');
  const [form,setForm]=useState<any>({host_location_id:'',name:'',field_space_type:STADIUM_TYPE,notes:'',is_active:true,supports_dynamic_configuration:true,grass30:0,grass53:0});
  const [stadiumSelections,setStadiumSelections]=useState<Record<string,boolean>>({'2x53':true});

  const load = async()=>{const [o,h,a,c]=await Promise.all([apiFetch('/organizations?page_size=500',{},token),apiFetch('/host-locations?page_size=500',{},token),apiFetch('/physical-field-areas?page_size=500',{},token),apiFetch('/field-configuration-options?page_size=2000',{},token)]); setOrgs(o.items||[]); setHosts(h.items||[]); setAreas(a.items||[]); setConfigs(c.items||[]);};
  useEffect(()=>{load().catch((e:any)=>{setType('err');setMessage(e.message||'Failed to load');});},[]);
  const hostOptions=useMemo(()=>hosts.filter((h:any)=>!orgId||h.organization_id===orgId),[hosts,orgId]);
  const visibleAreas = useMemo(()=>areas.filter((a:any)=>!form.host_location_id||a.host_location_id===form.host_location_id),[areas,form.host_location_id]);
  const configByArea = useMemo(()=>configs.reduce((m:any,c:any)=>((m[c.physical_field_area_id]=[...(m[c.physical_field_area_id]||[]),c]),m),{}),[configs]);

  const save = async()=>{
    try{
      if(!form.host_location_id||!form.name){setType('err');setMessage('Host location and area name are required.');return;}
      const area = await apiFetch('/physical-field-areas',{method:'POST',body:JSON.stringify({host_location_id:form.host_location_id,name:form.name,field_space_type:form.field_space_type,supports_dynamic_configuration:form.field_space_type===STADIUM_TYPE,notes:form.notes||null,is_active:form.is_active})},token);
      const configPayloads:any[] = [];
      if(form.field_space_type===STADIUM_TYPE){ for(const o of STADIUM_OPTIONS){ if(stadiumSelections[o.name]) configPayloads.push({physical_field_area_id:area.id,name:o.name,thirty_yard_capacity:o.thirty,fifty_three_yard_capacity:o.fiftyThree,is_active:true}); }}
      else { configPayloads.push({physical_field_area_id:area.id,name:'grass_custom',thirty_yard_capacity:Number(form.grass30)||0,fifty_three_yard_capacity:Number(form.grass53)||0,is_active:true}); }
      for(const payload of configPayloads){ await apiFetch('/field-configuration-options',{method:'POST',body:JSON.stringify(payload)},token); }
      setType('ok');setMessage('Physical field area saved.');
      setForm({...form,name:'',notes:'',grass30:0,grass53:0});
      await load();
    }catch(e:any){setType('err');setMessage(e.message||'Save failed');}
  };

  return <div className='space-y-4'>
    <Toast message={message} type={type}/><h1 className='text-2xl font-bold'>Physical Field Areas & Configurations</h1>
    <section className='rounded border p-4'><h2 className='mb-2 font-semibold'>Setup</h2>
      <div className='grid gap-2 md:grid-cols-2'>
        <select className='rounded border p-2' value={orgId} onChange={e=>setOrgId(e.target.value)}><option value=''>Select organization</option>{orgs.map((o:any)=><option key={o.id} value={o.id}>{o.name}</option>)}</select>
        <select className='rounded border p-2' value={form.host_location_id} onChange={e=>setForm({...form,host_location_id:e.target.value})}><option value=''>Select host location</option>{hostOptions.map((h:any)=><option key={h.id} value={h.id}>{h.name}</option>)}</select>
        <input className='rounded border p-2' placeholder='Physical field area name' value={form.name} onChange={e=>setForm({...form,name:e.target.value})}/>
        <select className='rounded border p-2' value={form.field_space_type} onChange={e=>setForm({...form,field_space_type:e.target.value})}><option value={STADIUM_TYPE}>Stadium Field</option><option value={GRASS_TYPE}>Grass/Park Field(s)</option></select>
        <input className='rounded border p-2 md:col-span-2' placeholder='Notes' value={form.notes} onChange={e=>setForm({...form,notes:e.target.value})}/>
      </div>
      {form.field_space_type===STADIUM_TYPE ? <div className='mt-3 space-y-2'><p className='text-sm font-medium'>Supported Stadium Configurations</p>{STADIUM_OPTIONS.map((o)=><label key={o.name} className='flex items-center gap-2 text-sm'><input type='checkbox' checked={!!stadiumSelections[o.name]} onChange={e=>setStadiumSelections({...stadiumSelections,[o.name]:e.target.checked})}/>{o.label}</label>)}</div> : <div className='mt-3 grid gap-2 md:grid-cols-2'><input type='number' className='rounded border p-2' placeholder='30-yard capacity' value={form.grass30} onChange={e=>setForm({...form,grass30:e.target.value})}/><input type='number' className='rounded border p-2' placeholder='53-yard capacity' value={form.grass53} onChange={e=>setForm({...form,grass53:e.target.value})}/></div>}
      <label className='mt-3 flex items-center gap-2 text-sm'><input type='checkbox' checked={form.is_active} onChange={e=>setForm({...form,is_active:e.target.checked})}/>Active</label>
      <button className='mt-3 rounded bg-emerald-700 px-4 py-2 text-white' onClick={save}>Save Physical Field Area</button>
    </section>
    <section className='rounded border p-4'><h2 className='mb-2 font-semibold'>Current Physical Field Areas</h2><div className='overflow-x-auto'><table className='w-full text-sm'><thead><tr><th className='border p-2 text-left'>Host Location</th><th className='border p-2 text-left'>Physical Field Area</th><th className='border p-2 text-left'>Type</th><th className='border p-2 text-left'>Supported Configurations</th><th className='border p-2 text-left'>Capacities</th><th className='border p-2'>Status</th></tr></thead><tbody>{visibleAreas.map((a:any)=>{const host=hosts.find((h:any)=>h.id===a.host_location_id); const rows=(configByArea[a.id]||[]); return <tr key={a.id}><td className='border p-2'>{host?.name||'Unknown'}</td><td className='border p-2'>{a.name}</td><td className='border p-2'>{a.field_space_type===STADIUM_TYPE?'Stadium Field':'Grass/Park Field(s)'}</td><td className='border p-2'>{rows.map((r:any)=>r.name).join(', ')||'—'}</td><td className='border p-2'>{rows.map((r:any)=>`30y:${r.thirty_yard_capacity} / 53y:${r.fifty_three_yard_capacity}`).join(' • ')||'—'}</td><td className='border p-2 text-center'>{a.is_active?'Active':'Inactive'}</td></tr>;})}</tbody></table></div></section>
  </div>
}
