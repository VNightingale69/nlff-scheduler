import CommunityLogo from '@/components/CommunityLogo';

type Props = {
  teamName: string;
  organizationName?: string | null;
  logoUrl?: string | null;
  logoAltText?: string | null;
  logoSize?: number;
  className?: string;
};

export default function TeamWithLogo({ teamName, organizationName, logoUrl, logoAltText, logoSize = 28, className = '' }: Props) {
  return <div className={`flex min-w-0 items-center gap-2 ${className}`}>
    <CommunityLogo
      src={logoUrl}
      name={organizationName || teamName}
      altText={logoAltText}
      size={logoSize}
      className='p-0.5'
    />
    <span className='min-w-0 break-words'>{teamName}</span>
  </div>;
}
