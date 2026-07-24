import type { RetailOffer } from './types';

export const AFFILIATE_PRE_DISCLOSURE_KO = '일부 판매처 링크는 광고·제휴 링크예요.';

export function offerCtaLabel(offer: RetailOffer): string {
  if (!offer.clickUrl) {
    return '구매 링크 준비 중';
  }
  return offer.linkType === 'retailer_search'
    ? `${offer.retailerName}에서 한국어로 검색`
    : `${offer.retailerName}에서 상품 확인`;
}

export function offerCtaAriaLabel(offer: RetailOffer): string {
  if (!offer.clickUrl) {
    return `${offer.retailerName} 구매 링크 준비 중`;
  }
  const relationship = offer.isAffiliate ? ', 광고·제휴 링크' : '';
  const destination = offer.linkType === 'retailer_search' ? '한국어 상품 검색 결과' : '상품 페이지';
  return `${offer.retailerName} ${destination} 열기, 토스 외부 이동${relationship}`;
}
