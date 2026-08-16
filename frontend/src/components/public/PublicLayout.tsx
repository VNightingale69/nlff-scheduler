import { ReactNode } from 'react';
import PublicFooter from './PublicFooter';
import PublicHeader from './PublicHeader';

export default function PublicLayout({ children }: { children: ReactNode }) {
  return <div className='flex min-h-screen flex-col'><PublicHeader /><div className='flex-1'>{children}</div><PublicFooter /></div>;
}
