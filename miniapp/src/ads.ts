import {
  loadFullScreenAd,
  showFullScreenAd,
} from '@apps-in-toss/web-framework';

export const TEST_INTERSTITIAL_AD_GROUP_ID = 'ait-ad-test-interstitial-id';

export const SEARCH_INTERSTITIAL_AD_GROUP_ID =
  import.meta.env.VITE_TOSS_INTERSTITIAL_AD_GROUP_ID?.trim()
  || TEST_INTERSTITIAL_AD_GROUP_ID;

type LoadFullScreenAd = typeof loadFullScreenAd;
type ShowFullScreenAd = typeof showFullScreenAd;

type SearchInterstitialControllerOptions = {
  adGroupId?: string;
  load?: LoadFullScreenAd;
  show?: ShowFullScreenAd;
  showTimeoutMs?: number;
};

export type SearchInterstitialController = {
  preload: () => void;
  showIfReady: () => Promise<boolean>;
  isReady: () => boolean;
  dispose: () => void;
};

/**
 * Preloads one interstitial and shows it only when a recommendation search
 * starts. Unsupported environments and ad failures never block the search.
 */
export function createSearchInterstitialController({
  adGroupId = SEARCH_INTERSTITIAL_AD_GROUP_ID,
  load = loadFullScreenAd,
  show = showFullScreenAd,
  showTimeoutMs = 65_000,
}: SearchInterstitialControllerOptions = {}): SearchInterstitialController {
  let state: 'idle' | 'loading' | 'ready' | 'showing' = 'idle';
  let unregisterLoad: (() => void) | undefined;
  let unregisterShow: (() => void) | undefined;
  let preloadTimer: ReturnType<typeof setTimeout> | undefined;

  function cleanupLoad() {
    unregisterLoad?.();
    unregisterLoad = undefined;
  }

  function cleanupShow() {
    unregisterShow?.();
    unregisterShow = undefined;
  }

  function supportsAd(functionWithSupport: { isSupported: () => boolean }) {
    try {
      return functionWithSupport.isSupported();
    } catch {
      return false;
    }
  }

  function preload() {
    if (state !== 'idle' || !adGroupId || !supportsAd(load)) {
      return;
    }

    state = 'loading';
    try {
      let loadFailedSynchronously = false;
      const unregister = load({
        options: { adGroupId },
        onEvent: (event) => {
          if (event.type === 'loaded') {
            state = 'ready';
          }
        },
        onError: () => {
          loadFailedSynchronously = true;
          state = 'idle';
          cleanupLoad();
        },
      });
      unregisterLoad = unregister;
      if (loadFailedSynchronously) {
        cleanupLoad();
      }
    } catch {
      state = 'idle';
      cleanupLoad();
    }
  }

  function scheduleNextPreload() {
    if (preloadTimer !== undefined) {
      return;
    }
    preloadTimer = setTimeout(() => {
      preloadTimer = undefined;
      preload();
    }, 0);
  }

  async function showIfReady(): Promise<boolean> {
    if (state !== 'ready' || !supportsAd(show)) {
      return false;
    }

    state = 'showing';
    cleanupLoad();

    return new Promise<boolean>((resolve) => {
      let settled = false;
      let displayed = false;
      const timeout = setTimeout(() => finish(false), showTimeoutMs);

      function finish(success: boolean) {
        if (settled) {
          return;
        }
        settled = true;
        clearTimeout(timeout);
        cleanupShow();
        state = 'idle';
        scheduleNextPreload();
        resolve(success);
      }

      try {
        const unregister = show({
          options: { adGroupId },
          onEvent: (event) => {
            if (event.type === 'show' || event.type === 'impression') {
              displayed = true;
            }
            if (event.type === 'dismissed') {
              finish(displayed);
            }
            if (event.type === 'failedToShow') {
              finish(false);
            }
          },
          onError: () => finish(false),
        });
        unregisterShow = unregister;
        if (settled) {
          cleanupShow();
        }
      } catch {
        finish(false);
      }
    });
  }

  function dispose() {
    cleanupLoad();
    cleanupShow();
    if (preloadTimer !== undefined) {
      clearTimeout(preloadTimer);
      preloadTimer = undefined;
    }
    state = 'idle';
  }

  return {
    preload,
    showIfReady,
    isReady: () => state === 'ready',
    dispose,
  };
}
