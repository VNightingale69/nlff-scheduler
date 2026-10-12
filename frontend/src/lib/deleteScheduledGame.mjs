// Keep persistence failure separate from refresh failure: a committed deletion
// must never be presented as a failed delete or restored by a stale response.
export async function deleteScheduledGame({ remove, commit, refresh, failed, refreshFailed }) {
  try {
    await remove();
  } catch (error) {
    failed(error);
    return;
  }
  commit();
  try {
    await refresh();
  } catch (error) {
    refreshFailed(error);
  }
}
