export type RemovableStorage = Pick<Storage, 'removeItem'>;

export interface DeleteUserDataResult {
  serverDeleted: boolean;
  deviceCleared: boolean;
  serverError?: unknown;
  deviceError?: unknown;
}

/**
 * Clear device-owned product data even when the server cannot be reached.
 *
 * The server delete function retains its session token on failure so the user
 * can retry later. All saved products and visible recommendation state can
 * still be removed from this device immediately.
 */
export async function deleteUserData(
  deleteServerData: () => Promise<void>,
  storage: RemovableStorage,
  localKeys: readonly string[],
): Promise<DeleteUserDataResult> {
  let deviceCleared = true;
  let deviceError: unknown;
  for (const key of localKeys) {
    try {
      storage.removeItem(key);
    } catch (error) {
      deviceCleared = false;
      deviceError ??= error;
    }
  }

  let serverDeleted = false;
  let serverError: unknown;
  try {
    await deleteServerData();
    serverDeleted = true;
  } catch (error) {
    serverError = error;
  }

  return { serverDeleted, deviceCleared, serverError, deviceError };
}
