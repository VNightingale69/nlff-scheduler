export const API_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000/api';

export async function apiFetch(path:string, opts:RequestInit={}, token?:string){
  const res = await fetch(`${API_URL}${path}`, { ...opts, headers: { 'Content-Type':'application/json', ...(token?{Authorization:`Bearer ${token}`}:{}) , ...(opts.headers||{}) }});
  if(!res.ok){ const t=await res.text(); throw new Error(t||'Request failed'); }
  return res.status===204?null:res.json();
}
