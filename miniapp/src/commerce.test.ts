import { describe, expect, it } from 'vitest';
import {
  AFFILIATE_PRE_DISCLOSURE_KO,
  offerCtaAriaLabel,
  offerCtaLabel,
  offerSearchLanguageLabel,
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
    linkType: 'product_page',
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
    expect(AFFILIATE_PRE_DISCLOSURE_KO).toBe(
      '이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.',
    );
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

  it('labels retailer search results without claiming an exact product page', () => {
    const search = offer({
      retailerName: '네이버쇼핑',
      linkType: 'retailer_search',
      isAffiliate: false,
    });

    expect(offerCtaLabel(search)).toBe('네이버쇼핑에서 한국어로 검색');
    expect(offerCtaAriaLabel(search)).toBe(
      '네이버쇼핑 한국어 상품 검색 결과 열기, 토스 외부 이동',
    );
  });

  it('labels YesStyle as an English-language retailer search', () => {
    const search = offer({
      retailerName: 'YesStyle',
      linkType: 'retailer_search',
      isAffiliate: false,
    });

    expect(offerSearchLanguageLabel(search)).toBe('영문');
    expect(offerCtaLabel(search)).toBe('YesStyle에서 영문으로 검색');
    expect(offerCtaAriaLabel(search)).toBe(
      'YesStyle 영문 상품 검색 결과 열기, 토스 외부 이동',
    );
  });
});
