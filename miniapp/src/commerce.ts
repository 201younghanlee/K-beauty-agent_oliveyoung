import type { RetailOffer } from './types';

export const AFFILIATE_PRE_DISCLOSURE_KO = '일부 판매처 링크는 광고·제휴 링크예요.';

export function offerCtaLabel(offer: RetailOffer): string {
  return offer.clickUrl ? `${offer.retailerName}에서 상품 확인` : '구매 링크 준비 중';
}

export function offerCtaAriaLabel(offer: RetailOffer): string {
  if (!offer.clickUrl) {
    return `${offer.retailerName} 구매 링크 준비 중`;
  }
  const relationship = offer.isAffiliate ? ', 광고·제휴 링크' : '';
  return `${offer.retailerName} 상품 페이지 열기, 토스 외부 이동${relationship}`;
}
