'use client';
import { useEffect, useState } from 'react';
import Link from 'next/link';
import { API_URL } from '@/lib/api';
import { APP_NAME } from '@/config/branding';
import PublicLayout from '@/components/public/PublicLayout';

type Rulebook = { original_filename: string; file_size_bytes: number; view_url: string; download_url: string; file_url?: string | null; };
const formatBytes = (bytes: number) => `${(bytes / 1024 / (bytes >= 1024 * 1024 ? 1024 : 1)).toFixed(1)} ${bytes >= 1024 * 1024 ? 'MB' : 'KB'}`;
const rulebookUrl = (path?: string | null) => { if (!path) return '#'; if (/^https?:\/\//.test(path)) return path; const normalizedPath = path.startsWith('/api/') ? path.slice(4) : path; return `${API_URL}${normalizedPath.startsWith('/') ? normalizedPath : `/${normalizedPath}`}`; };
function Resource({ title, description, document, viewLabel }: { title: string; description: string; document: Rulebook; viewLabel: string }) { return <section className='rounded border bg-white p-4 shadow-sm'><h2 className='text-lg font-semibold'>{title}</h2><p className='mt-1 text-sm text-slate-600'>{description}</p><p className='mt-2 text-sm'>{document.original_filename} · {formatBytes(document.file_size_bytes)}</p><div className='mt-4 flex gap-2'><a className='rounded bg-slate-800 px-3 py-2 text-white' href={rulebookUrl(document.view_url || document.file_url)} target='_blank' rel='noreferrer'>{viewLabel}</a><a className='rounded border px-3 py-2' href={rulebookUrl(document.download_url)}>Download PDF</a></div></section>; }
export default function PublicRulebookPage() {
 const [rulebook,setRulebook]=useState<Rulebook|null>(null); const [infographic,setInfographic]=useState<Rulebook|null>(null); const [loading,setLoading]=useState(true); const [message,setMessage]=useState('');
 useEffect(()=>{Promise.all(['/public/rulebook','/public/rule-infographic'].map(async path=>{const r=await fetch(`${API_URL}${path}`); if(r.status===404)return null; if(!r.ok)throw new Error(); return r.json();})).then(([r,i])=>{setRulebook(r);setInfographic(i);if(!r)setMessage('No rulebook has been uploaded yet.');}).catch(()=>setMessage('Unable to load league rules. Please try again later.')).finally(()=>setLoading(false));},[]);
 return <PublicLayout><main className='mx-auto max-w-4xl space-y-4 p-4'><div className='flex items-center justify-between gap-3'><div><h1 className='text-2xl font-bold'>League Rules</h1><p className='text-sm text-slate-600'>{APP_NAME}</p></div><Link className='rounded border px-3 py-2 text-sm' href='/schedule'>Published Schedule</Link></div>{loading&&<div className='rounded border p-4'>Loading league rules...</div>}{!loading&&message&&<div className='rounded border p-4'>{message}</div>}{rulebook&&<Resource title='Official Rulebook' description='Complete league rules and regulations.' document={rulebook} viewLabel='View Rulebook' />}{infographic&&<Resource title='Rule Infographic' description='Quick-reference guide for scoring and commonly used game rules.' document={infographic} viewLabel='View Infographic' />}</main></PublicLayout>;
}
