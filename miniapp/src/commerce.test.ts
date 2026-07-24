import { describe, expect, it } from 'vitest';
import {
  AFFILIATE_PRE_DISCLOSURE_KO,
  offerCtaAriaLabel,
  offerCtaLabel,
} from './commerce';
import type { RetailOffer } from './types';

function offer(overrides: Partial<RetailOffer> = {}): RetailOffer {
  return {
    id: 'coupang-offer',
    retailerId: 'coupang',
    retailerName: '쿠팡',
    currency: 'KRW',
    availability: 'unknown',
    isStale: false,
    clickUrl: 'https://api.example.test/r/signed-token',
    isLinkOnly: true,
    isAffiliate: true,
    ...overrides,
  };
}

describe('affiliate retailer calls to action', () => {
  it('names the destination and discloses the external affiliate relationship', () => {
    const coupang = offer();

    expect(offerCtaLabel(coupang)).toBe('쿠팡에서 상품 확인');
    expect(offerCtaAriaLabel(coupang)).toBe(
      '쿠팡 상품 페이지 열기, 토스 외부 이동, 광고·제휴 링크',
    );
    expect(AFFILIATE_PRE_DISCLOSURE_KO).toBe('일부 판매처 링크는 광고·제휴 링크예요.');
  });

  it('does not call a non-affiliate retailer link an affiliate link', () => {
    expect(offerCtaAriaLabel(offer({ retailerName: 'Olive Young', isAffiliate: false }))).toBe(
      'Olive Young 상품 페이지 열기, 토스 외부 이동',
    );
  });

  it('announces a disabled link without claiming that it can open', () => {
    const unavailable = offer({ clickUrl: undefined });

    expect(offerCtaLabel(unavailable)).toBe('구매 링크 준비 중');
    expect(offerCtaAriaLabel(unavailable)).toBe('쿠팡 구매 링크 준비 중');
  });
});
