import CrudPage from '@/components/CrudPage';
import { ENTITIES } from '@/config/entities';

export default function Page(){
  const config = ENTITIES['divisions'];
  return <CrudPage title={config.title} path={config.path} fields={config.fields} />;
}
