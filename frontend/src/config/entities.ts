export type EntityConfig = {
  title: string;
  path: string;
  fields: { key: string; label: string; type?: 'text' | 'number' | 'date' | 'time' | 'checkbox' | 'select' }[];
  nav: boolean;
  roles?: ('league_admin' | 'community_scheduler')[];
};

export const ENTITIES: Record<string, EntityConfig> = {
  organizations: { title: 'Organizations', path: '/organizations', nav: true, fields: [{ key: 'name', label: 'Name' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  divisions: { title: 'Divisions', path: '/divisions', nav: true, fields: [{ key: 'name', label: 'Name' }, { key: 'required_field_layout_type', label: 'Required field layout', type: 'select' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  'host-locations': { title: 'Host Locations', path: '/host-locations', nav: true, fields: [{ key: 'organization_id', label: 'Organization ID' }, { key: 'name', label: 'Name' }, { key: 'address', label: 'Address' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  fields: { title: 'Fields', path: '/fields', nav: true, fields: [{ key: 'host_location_id', label: 'Host Location', type: 'select' }, { key: 'name', label: 'Name' }, { key: 'layout_type', label: 'Layout Type', type: 'select' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  teams: { title: 'Teams', path: '/teams', nav: true, fields: [{ key: 'organization_id', label: 'Organization', type: 'select' }, { key: 'division_id', label: 'Division', type: 'select' }, { key: 'name', label: 'Name' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  games: { title: 'Games', path: '/games', nav: true, roles: ['league_admin'], fields: [] },
  'hosting-availability': { title: 'Hosting Availability', path: '/hosting-availabilities', nav: true, fields: [{ key: 'field_id', label: 'Field ID' }, { key: 'available_date', label: 'Available Date', type: 'date' }, { key: 'start_time', label: 'Start Time', type: 'time' }, { key: 'end_time', label: 'End Time', type: 'time' }, { key: 'is_available', label: 'Is Available', type: 'checkbox' }] },
};
