export type EntityConfig = {
  title: string;
  path: string;
  fields: { key: string; label: string; type?: 'text' | 'number' | 'date' | 'time' | 'checkbox' | 'select' }[];
  nav: boolean;
  roles?: ('league_admin' | 'community_scheduler')[];
};

export const ENTITIES: Record<string, EntityConfig> = {
  organizations: { title: 'Organizations', path: '/organizations', nav: true, fields: [{ key: 'name', label: 'Name' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  divisions: { title: 'Community Division Participation', path: '/divisions', nav: true, fields: [{ key: 'name', label: 'Name' }] },
  'host-locations': { title: 'Host Locations', path: '/host-locations', nav: true, fields: [{ key: 'organization_id', label: 'Organization', type: 'select' }, { key: 'name', label: 'Name' }, { key: 'address_line1', label: 'Street Address' }, { key: 'address_line2', label: 'Address Line 2' }, { key: 'city', label: 'City' }, { key: 'state', label: 'State' }, { key: 'zip_code', label: 'Zip Code' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  fields: { title: 'Fields', path: '/fields', nav: true, fields: [{ key: 'host_location_id', label: 'Host Location', type: 'select' }, { key: 'name', label: 'Name' }, { key: 'layout_type', label: 'Layout Type', type: 'select' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  teams: { title: 'Teams', path: '/teams', nav: true, fields: [{ key: 'organization_id', label: 'Organization', type: 'select' }, { key: 'division_id', label: 'Division', type: 'select' }, { key: 'name', label: 'Name' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  seasons: { title: 'Seasons', path: '/seasons', nav: true, fields: [{ key: 'name', label: 'Name' }, { key: 'start_date', label: 'Start Date', type: 'date' }, { key: 'end_date', label: 'End Date', type: 'date' }, { key: 'is_active', label: 'Active', type: 'checkbox' }] },
  weeks: { title: 'Season Weeks / Game Dates', path: '/weeks', nav: true, fields: [{ key: 'season_id', label: 'Season', type: 'select' }, { key: 'week_number', label: 'Week Number', type: 'number' }, { key: 'start_date', label: 'Start Date', type: 'date' }, { key: 'end_date', label: 'End Date', type: 'date' }] },
  games: { title: 'Games', path: '/games', nav: true, roles: ['league_admin'], fields: [] },
  'hosting-availability': { title: 'Hosting Availability', path: '/hosting-availabilities', nav: true, fields: [{ key: 'field_id', label: 'Field ID' }, { key: 'available_date', label: 'Available Date', type: 'date' }, { key: 'start_time', label: 'Start Time', type: 'time' }, { key: 'end_time', label: 'End Time', type: 'time' }, { key: 'is_available', label: 'Is Available', type: 'checkbox' }] },
  'host-availability-matrix': { title: 'Host Availability Matrix', path: '/host-availability-matrix', nav: true, roles: ['league_admin'], fields: [] },
  'generated-slots': { title: 'Generated Slots', path: '/generated-game-slots', nav: true, fields: [] },
  'schedule-readiness': { title: 'Schedule Readiness', path: '/schedule-readiness', nav: true, fields: [] },
  'manual-schedule-builder': { title: 'Manual Schedule Builder', path: '/manual-schedule-builder', nav: true, fields: [] },
  'schedule-management': { title: 'Schedule Management', path: '/schedule-management', nav: true, fields: [] },
  'game-statuses': { title: 'Game Statuses', path: '/game-statuses', nav: true, roles: ['league_admin'], fields: [] },
};
