import { describe, expect, it, vi } from 'vitest';
import {
  createSearchInterstitialController,
  TEST_INTERSTITIAL_AD_GROUP_ID,
} from './ads';

type LoadParams = Parameters<
  typeof import('@apps-in-toss/web-framework').loadFullScreenAd
>[0];
type ShowParams = Parameters<
  typeof import('@apps-in-toss/web-framework').showFullScreenAd
>[0];

function supportedBridge<T extends (...args: never[]) => unknown>(implementation: T) {
  return Object.assign(vi.fn(implementation), {
    isSupported: vi.fn(() => true),
  });
}

describe('search interstitial ads', () => {
  it('preloads the official test ad and resolves after the displayed ad is dismissed', async () => {
    let loadParams: LoadParams | undefined;
    let showParams: ShowParams | undefined;
    const load = supportedBridge((params: LoadParams) => {
      loadParams = params;
      return vi.fn();
    });
    const show = supportedBridge((params: ShowParams) => {
      showParams = params;
      return vi.fn();
    });
    const controller = createSearchInterstitialController({
      load: load as unknown as typeof import('@apps-in-toss/web-framework').loadFullScreenAd,
      show: show as unknown as typeof import('@apps-in-toss/web-framework').showFullScreenAd,
    });

    controller.preload();
    expect(loadParams?.options?.adGroupId).toBe(TEST_INTERSTITIAL_AD_GROUP_ID);
    loadParams?.onEvent({ type: 'loaded' });
    expect(controller.isReady()).toBe(true);

    const shown = controller.showIfReady();
    expect(showParams?.options?.adGroupId).toBe(TEST_INTERSTITIAL_AD_GROUP_ID);
    showParams?.onEvent({ type: 'show' });
    showParams?.onEvent({ type: 'impression' });
    showParams?.onEvent({ type: 'dismissed' });

    await expect(shown).resolves.toBe(true);
  });

  it('does not block a search when ads are unsupported or not ready', async () => {
    const load = Object.assign(vi.fn(() => vi.fn()), {
      isSupported: vi.fn(() => false),
    });
    const show = Object.assign(vi.fn(() => vi.fn()), {
      isSupported: vi.fn(() => false),
    });
    const controller = createSearchInterstitialController({
      load: load as unknown as typeof import('@apps-in-toss/web-framework').loadFullScreenAd,
      show: show as unknown as typeof import('@apps-in-toss/web-framework').showFullScreenAd,
    });

    controller.preload();

    expect(load).not.toHaveBeenCalled();
    await expect(controller.showIfReady()).resolves.toBe(false);
    expect(show).not.toHaveBeenCalled();
  });

  it('continues after an ad fails to show', async () => {
    let loadParams: LoadParams | undefined;
    let showParams: ShowParams | undefined;
    const load = supportedBridge((params: LoadParams) => {
      loadParams = params;
      return vi.fn();
    });
    const show = supportedBridge((params: ShowParams) => {
      showParams = params;
      return vi.fn();
    });
    const controller = createSearchInterstitialController({
      load: load as unknown as typeof import('@apps-in-toss/web-framework').loadFullScreenAd,
      show: show as unknown as typeof import('@apps-in-toss/web-framework').showFullScreenAd,
    });

    controller.preload();
    loadParams?.onEvent({ type: 'loaded' });
    const shown = controller.showIfReady();
    showParams?.onEvent({ type: 'failedToShow' });

    await expect(shown).resolves.toBe(false);
  });
});
