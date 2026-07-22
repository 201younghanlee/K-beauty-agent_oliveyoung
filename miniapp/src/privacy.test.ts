import { describe, expect, it, vi } from 'vitest';
import { deleteUserData } from './privacy';

describe('deleteUserData', () => {
  it('clears every local product key when remote deletion fails', async () => {
    const remoteError = new Error('server unavailable');
    const removeItem = vi.fn();
    const keys = ['saved-ids', 'saved-cache', 'saved-issued-at'];

    const result = await deleteUserData(
      vi.fn().mockRejectedValue(remoteError),
      { removeItem },
      keys,
    );

    expect(removeItem.mock.calls.map(([key]) => key)).toEqual(keys);
    expect(result).toEqual({
      serverDeleted: false,
      deviceCleared: true,
      serverError: remoteError,
      deviceError: undefined,
    });
  });

  it('continues clearing keys after an individual device-storage error', async () => {
    const removeItem = vi.fn()
      .mockImplementationOnce(() => { throw new Error('blocked key'); })
      .mockImplementation(() => undefined);

    const result = await deleteUserData(
      vi.fn().mockResolvedValue(undefined),
      { removeItem },
      ['first', 'second'],
    );

    expect(removeItem).toHaveBeenCalledTimes(2);
    expect(result.serverDeleted).toBe(true);
    expect(result.deviceCleared).toBe(false);
  });

  it('clears local keys before a pending server request resolves', async () => {
    let finishRemoteDelete: (() => void) | undefined;
    const remoteDelete = new Promise<void>((resolve) => {
      finishRemoteDelete = resolve;
    });
    const removeItem = vi.fn();

    const deletion = deleteUserData(
      () => remoteDelete,
      { removeItem },
      ['saved'],
    );

    expect(removeItem).toHaveBeenCalledWith('saved');
    finishRemoteDelete?.();
    await expect(deletion).resolves.toMatchObject({ serverDeleted: true, deviceCleared: true });
  });
});
