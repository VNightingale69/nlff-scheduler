'use client';

type Props = { label: string; type?: string; value: any; onChange: (value: any) => void };

export default function FormField({ label, type = 'text', value, onChange }: Props) {
  if (type === 'checkbox') {
    return <label className='flex items-center gap-2 text-sm'><input type='checkbox' checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} /> {label}</label>;
  }
  return (
    <label className='text-sm'>
      <span className='mb-1 block font-medium'>{label}</span>
      <input className='w-full rounded border p-2' type={type} value={value ?? ''} onChange={(e) => onChange(type === 'number' ? Number(e.target.value) : e.target.value)} />
    </label>
  );
}
