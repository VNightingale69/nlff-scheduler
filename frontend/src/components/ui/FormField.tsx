'use client';

type Option = { value: string; label: string };
type Props = { label: string; type?: string; value: any; onChange: (value: any) => void; options?: Option[] };

export default function FormField({ label, type = 'text', value, onChange, options }: Props) {
  if (type === 'checkbox') return <label className='flex items-center gap-2 text-sm'><input type='checkbox' checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} /> {label}</label>;
  if (type === 'select') return <label className='text-sm'><span className='mb-1 block font-medium'>{label}</span><select className='w-full rounded border p-2' value={value ?? ''} onChange={(e) => onChange(e.target.value)}><option value=''>Select {label}</option>{(options||[]).map((o)=><option key={o.value} value={o.value}>{o.label}</option>)}</select></label>;
  return <label className='text-sm'><span className='mb-1 block font-medium'>{label}</span><input className='w-full rounded border p-2' type={type} value={value ?? ''} onChange={(e) => onChange(type === 'number' ? Number(e.target.value) : e.target.value)} /></label>;
}
