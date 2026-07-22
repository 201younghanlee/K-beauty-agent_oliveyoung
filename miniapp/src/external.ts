import { openURL } from '@apps-in-toss/web-framework';

export async function openExternalUrl(url: string): Promise<void> {
  if (!url.startsWith('https://')) {
    throw new Error('안전한 외부 주소를 확인할 수 없어요.');
  }

  const hasNativeBridge = Boolean((window as Window & { ReactNativeWebView?: unknown }).ReactNativeWebView);
  if (!hasNativeBridge) {
    const popup = window.open('', '_blank');
    if (!popup) {
      throw new Error('브라우저에서 새 창 열기를 허용해 주세요.');
    }
    popup.opener = null;
    popup.location.replace(url);
    return;
  }

  try {
    await openURL(url);
  } catch {
    throw new Error('외부 페이지를 열지 못했어요. 잠시 후 다시 시도해 주세요.');
  }
}
