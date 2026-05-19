'use client';

export default function Toast({ message, type }: { message: string; type: 'ok' | 'err' }) {
  if (!message) return null;
  return <div className={`fixed right-4 top-4 z-50 rounded px-4 py-2 text-white shadow ${type === 'ok' ? 'bg-emerald-600' : 'bg-rose-600'}`}>{message}</div>;
}
