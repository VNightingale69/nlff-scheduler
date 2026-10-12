export function deleteScheduledGame(actions: {
  remove: () => Promise<unknown>;
  commit: () => void;
  refresh: () => Promise<unknown>;
  failed: (error: unknown) => void;
  refreshFailed: (error: unknown) => void;
}): Promise<void>;
