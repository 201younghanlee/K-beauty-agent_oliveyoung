import { graniteEvent } from '@apps-in-toss/web-framework';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react';
import {
  deleteAnonymousSessionData,
  ingredientSelectionConflicts,
  privacyPolicyUrl,
  requestProductOffers,
  requestRecommendations,
} from './api';
import { openExternalUrl } from './external';
import { deleteUserData } from './privacy';
import { hasVerifiedReviewMetrics, sourceUrlIsProductSource } from './provenance';
import { routeAnnouncement, type AppScreen } from './accessibility';
import type {
  Product,
  ProductExternalLink,
  RecommendationItem,
  RecommendationResult,
  RetailOffer,
  SurveyAnswers,
} from './types';
import { useSafeAreaInsets } from './useSafeArea';

const LEGACY_SAVED_STORAGE_KEY = 'kBeautyAgentSavedProductsV1';
const SAVED_IDS_STORAGE_KEY = 'kBeautyAgentSavedProductIdsV2';
const SAVED_CACHE_STORAGE_KEY = 'kBeautyAgentSavedProductCacheV2';
const SAVED_ISSUED_AT_KEY = 'kBeautyAgentSavedProductIssuedAtV2';
const SAVED_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
const VALIDATION_MESSAGE_ID = 'survey-validation-message';
const SKIN_QUESTION_TITLE_ID = 'skin-question-title';
const SENSITIVITY_QUESTION_TITLE_ID = 'sensitivity-question-title';
const CATEGORY_QUESTION_TITLE_ID = 'category-question-title';
const PRIMARY_CONCERN_TITLE_ID = 'primary-concern-title';
const INGREDIENT_QUESTION_TITLE_ID = 'ingredient-question-title';
const OBF_DATA_LICENSE_URL = 'https://opendatacommons.org/licenses/odbl/1-0/';
const OBF_IMAGE_LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/3.0/';
const OBF_DATA_URL = 'https://world.openbeautyfacts.org/data';

const SKIN_OPTIONS = [
  { value: 'oily', label: '지성' },
  { value: 'dry', label: '건성' },
  { value: 'combination', label: '복합성' },
  { value: 'normal', label: '중성' },
  { value: 'unknown', label: '잘 모르겠어요' },
] as const;

const SENSITIVITY_OPTIONS = [
  { value: 'frequent', label: '쉽게 따갑거나 붉어져요' },
  { value: 'occasional', label: '가끔 예민해져요' },
  { value: 'low', label: '거의 민감하지 않아요' },
] as const;

const CATEGORY_OPTIONS = [
  { value: 'cleanser', label: '클렌저', icon: '🫧' },
  { value: 'toner', label: '토너·패드', icon: '💧' },
  { value: 'serum', label: '세럼·앰플', icon: '✨' },
  { value: 'moisturizer', label: '로션·크림', icon: '🧴' },
  { value: 'sunscreen', label: '선케어', icon: '☀️' },
  { value: 'basic', label: '잘 모르겠어요', icon: '🧴' },
] as const;

const CONCERN_OPTIONS = [
  { value: 'acne', label: '트러블·여드름' },
  { value: 'oil_control', label: '유분·번들거림' },
  { value: 'hydration', label: '속건조·당김' },
  { value: 'dryness', label: '건조·각질' },
  { value: 'barrier_support', label: '장벽 약화·쉽게 따가움' },
  { value: 'redness', label: '붉은기·민감' },
  { value: 'hyperpigmentation', label: '잡티·트러블 흔적' },
  { value: 'clogged_pores', label: '모공·블랙헤드' },
  { value: 'dullness', label: '칙칙함·톤 불균일' },
  { value: 'texture', label: '피부결·거칠음' },
  { value: 'anti_aging', label: '탄력·잔주름' },
] as const;

const TEXTURE_OPTIONS = [
  { value: 'watery', label: '워터리' },
  { value: 'gel', label: '젤' },
  { value: 'lotion', label: '로션' },
  { value: 'cream', label: '크림' },
  { value: 'rich', label: '밤·리치' },
] as const;

const FINISH_OPTIONS = [
  { value: 'fresh', label: '산뜻함' },
  { value: 'low_sticky', label: '끈적임 적음' },
  { value: 'moist', label: '촉촉함' },
  { value: 'glow', label: '쫀쫀·윤기' },
  { value: 'matte', label: '보송함' },
] as const;

const BUDGET_OPTIONS = [
  { value: null, label: '제한 없음' },
  { value: 20_000, label: '2만원 이하' },
  { value: 30_000, label: '3만원 이하' },
  { value: 50_000, label: '5만원 이하' },
] as const;

const AVOID_OPTIONS = [
  { value: 'fragrance', label: '향료' },
  { value: 'ethanol', label: '에탄올' },
  { value: 'retinol', label: '레티노이드' },
  { value: 'salicylic acid', label: '살리실산' },
] as const;

const PREFERRED_OPTIONS = [
  { value: 'niacinamide', label: '나이아신아마이드' },
  { value: 'hyaluronic acid', label: '히알루론산' },
  { value: 'ceramide', label: '세라마이드' },
  { value: 'panthenol', label: '판테놀' },
  { value: 'centella asiatica', label: '병풀·시카' },
  { value: 'retinol', label: '레티놀' },
  { value: 'salicylic acid', label: '살리실산' },
] as const;

const INITIAL_ANSWERS: SurveyAnswers = {
  skinType: '',
  sensitivity: '',
  category: '',
  primaryConcern: '',
  concerns: [],
  texture: '',
  finish: '',
  budget: null,
  preferredIngredients: [],
  preferredIngredientsText: '',
  avoidIngredients: [],
  avoidIngredientsText: '',
  privacyConsent: false,
};

type Screen = AppScreen;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === 'string');
}

function isOptionalString(value: unknown): boolean {
  return value === undefined || typeof value === 'string';
}

function isOptionalNumber(value: unknown): boolean {
  return value === undefined || (typeof value === 'number' && Number.isFinite(value));
}

function isOptionalStringArray(value: unknown): boolean {
  return value === undefined || isStringArray(value);
}

function isSavedIngredientExplanations(value: unknown): boolean {
  if (value === undefined) {
    return true;
  }
  return Array.isArray(value) && value.length <= 80 && value.every((explanation) => (
    isRecord(explanation)
    && typeof explanation.name === 'string'
    && typeof explanation.label === 'string'
    && isOptionalString(explanation.displayNameKo)
    && isStringArray(explanation.supports)
    && isStringArray(explanation.displaySupportsKo)
    && isStringArray(explanation.cautions)
    && isStringArray(explanation.displayCautionsKo)
    && isOptionalString(explanation.evidenceLevel)
    && isOptionalString(explanation.rationale)
    && isOptionalString(explanation.displayRationaleKo)
  ));
}

function isSavedDataConfidence(value: unknown): boolean {
  if (value === undefined) {
    return true;
  }
  if (!isRecord(value)
    || !['high', 'medium', 'low'].includes(String(value.level))
    || typeof value.labelKo !== 'string'
    || !isRecord(value.factors)) {
    return false;
  }
  return Object.values(value.factors).every((factor) => factor === undefined || (
    isRecord(factor)
    && typeof factor.status === 'string'
    && typeof factor.labelKo === 'string'
    && isOptionalString(factor.checkedAt)
    && isOptionalString(factor.dateKind)
    && isOptionalString(factor.sourceUrl)
  ));
}

function isSavedExternalLinks(value: unknown): value is ProductExternalLink[] | undefined {
  if (value === undefined) {
    return true;
  }
  if (!Array.isArray(value) || value.length > 8) {
    return false;
  }
  const allowedKinds = new Set<ProductExternalLink['kind']>([
    'brand_official',
    'ingredient_reference',
    'data_reference',
    'review_reference',
  ]);
  return value.every((link) => {
    if (!isRecord(link)
      || !allowedKinds.has(link.kind as ProductExternalLink['kind'])
      || typeof link.label !== 'string'
      || !link.label
      || link.label.length > 120
      || typeof link.provider !== 'string'
      || !link.provider
      || link.provider.length > 80
      || typeof link.url !== 'string'
      || link.url.length > 2_048) {
      return false;
    }
    try {
      const parsed = new URL(link.url);
      return parsed.protocol === 'https:'
        && !parsed.username
        && !parsed.password
        && parsed.toString() === link.url;
    } catch {
      return false;
    }
  });
}

function isSavedRecommendationItem(value: unknown): value is RecommendationItem {
  if (!isRecord(value) || !isRecord(value.product)) {
    return false;
  }

  const { product } = value;
  return (
    typeof product.id === 'string' && product.id.length > 0 &&
    typeof product.name === 'string' && product.name.length > 0 &&
    typeof product.brand === 'string' &&
    typeof product.category === 'string' &&
    isOptionalString(product.displayNameKo) &&
    isOptionalString(product.imageUrl) &&
    isOptionalString(product.oliveyoungUrl) &&
    isOptionalString(product.purchaseUrl) &&
    isOptionalString(product.sourceUrl) &&
    isOptionalString(product.officialUrl) &&
    isOptionalString(product.retailerName) &&
    isOptionalString(product.catalogSource) &&
    isOptionalString(product.sourceUpdatedAt) &&
    isOptionalString(product.priceCheckedAt) &&
    isOptionalString(product.reviewSourceUrl) &&
    isOptionalString(product.ingredientStatus) &&
    isOptionalString(product.recommendationTier) &&
    isOptionalString(product.dataLicense) &&
    isOptionalString(product.dataAttributionUrl) &&
    isSavedExternalLinks(product.externalLinks) &&
    isOptionalNumber(product.priceKrw) &&
    isOptionalNumber(product.rating) &&
    isOptionalNumber(product.reviewCount) &&
    isOptionalString(product.reviewSummary) &&
    isOptionalString(product.reviewVerifiedAt) &&
    isStringArray(product.ingredients) &&
    isOptionalStringArray(product.claims) &&
    isOptionalStringArray(product.concerns) &&
    isOptionalStringArray(product.textureTags) &&
    isSavedIngredientExplanations(product.ingredientExplanations) &&
    (product.offers === undefined || Array.isArray(product.offers)) &&
    typeof value.reason === 'string' &&
    isOptionalNumber(value.score) &&
    isOptionalStringArray(value.reasons) &&
    isStringArray(value.cautions) &&
    isStringArray(value.matchedIngredients) &&
    isOptionalStringArray(value.missingData) &&
    isSavedDataConfidence(value.dataConfidence)
  );
}

function withSavedDefaults(item: RecommendationItem): RecommendationItem {
  return {
    ...item,
    reasons: item.reasons?.length ? item.reasons : item.reason ? [item.reason] : [],
    missingData: item.missingData ?? [],
    product: {
      ...item.product,
      claims: item.product.claims ?? [],
      concerns: item.product.concerns ?? [],
      textureTags: item.product.textureTags ?? [],
      ingredientExplanations: item.product.ingredientExplanations ?? [],
      offers: item.product.offers ?? [],
    },
  };
}

function withoutDynamicOfferData(item: RecommendationItem): RecommendationItem {
  return {
    ...item,
    product: {
      ...item.product,
      oliveyoungUrl: undefined,
      purchaseUrl: undefined,
      retailerName: undefined,
      priceKrw: undefined,
      priceCheckedAt: undefined,
      commerce: undefined,
      offers: [],
    },
  };
}

function readLegacySavedItems(): RecommendationItem[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(LEGACY_SAVED_STORAGE_KEY) || '[]');
    if (!Array.isArray(value)) {
      return [];
    }

    const seenIds = new Set<string>();
    const items: RecommendationItem[] = [];
    value.forEach((item) => {
      if (!isSavedRecommendationItem(item) || seenIds.has(item.product.id)) {
        return;
      }
      seenIds.add(item.product.id);
      items.push(withSavedDefaults(item));
    });
    return items;
  } catch {
    return [];
  }
}

function readSavedState(): { ids: string[]; cache: Record<string, RecommendationItem> } {
  try {
    const hasStoredData = [LEGACY_SAVED_STORAGE_KEY, SAVED_IDS_STORAGE_KEY, SAVED_CACHE_STORAGE_KEY]
      .some((key) => window.localStorage.getItem(key) !== null);
    const issuedAt = Number(window.localStorage.getItem(SAVED_ISSUED_AT_KEY));
    const isExpired = !Number.isFinite(issuedAt)
      || issuedAt <= 0
      || issuedAt > Date.now()
      || Date.now() - issuedAt > SAVED_MAX_AGE_MS;
    if (hasStoredData && isExpired) {
      for (const key of [
        LEGACY_SAVED_STORAGE_KEY,
        SAVED_IDS_STORAGE_KEY,
        SAVED_CACHE_STORAGE_KEY,
        SAVED_ISSUED_AT_KEY,
      ]) {
        window.localStorage.removeItem(key);
      }
      return { ids: [], cache: {} };
    }
  } catch {
    return { ids: [], cache: {} };
  }
  const legacyItems = readLegacySavedItems().map(withoutDynamicOfferData);
  let ids: string[] = [];
  let rawCache: unknown = {};
  let hasSavedIds = false;

  try {
    const storedIds = window.localStorage.getItem(SAVED_IDS_STORAGE_KEY);
    hasSavedIds = storedIds !== null;
    const parsedIds: unknown = JSON.parse(storedIds || '[]');
    if (Array.isArray(parsedIds)) {
      ids = [...new Set(parsedIds.filter((id): id is string => typeof id === 'string' && id.length > 0))];
    }
    rawCache = JSON.parse(window.localStorage.getItem(SAVED_CACHE_STORAGE_KEY) || '{}');
  } catch {
    // 잘못된 로컬 데이터는 레거시 찜 목록으로 복구합니다.
  }

  if (!hasSavedIds) {
    ids = legacyItems.map((item) => item.product.id);
  }

  const cache: Record<string, RecommendationItem> = {};
  if (isRecord(rawCache)) {
    Object.entries(rawCache).forEach(([id, value]) => {
      if (ids.includes(id) && isSavedRecommendationItem(value)) {
        cache[id] = withoutDynamicOfferData(withSavedDefaults(value));
      }
    });
  }
  legacyItems.forEach((item) => {
    cache[item.product.id] ??= item;
  });
  return { ids, cache };
}

function savedItemPlaceholder(productId: string): RecommendationItem {
  return {
    product: {
      id: productId,
      name: '저장한 제품',
      brand: '제품 정보 새로고침 필요',
      category: 'skincare',
      ingredients: [],
      claims: [],
      concerns: [],
      textureTags: [],
      ingredientExplanations: [],
      offers: [],
    },
    reason: '추천을 다시 실행하면 최신 제품 정보를 확인할 수 있어요.',
    reasons: ['추천을 다시 실행하면 최신 제품 정보를 확인할 수 있어요.'],
    cautions: [],
    matchedIngredients: [],
    missingData: [],
  };
}

function formatPrice(price?: number, currency = 'KRW'): string {
  if (price === undefined) {
    return '판매가 미제공';
  }
  if (currency === 'KRW') {
    return `${new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 }).format(price)}원`;
  }
  try {
    return new Intl.NumberFormat('ko-KR', {
      style: 'currency',
      currency,
      maximumFractionDigits: currency === 'KRW' ? 0 : 2,
    }).format(price);
  } catch {
    return `${new Intl.NumberFormat('ko-KR').format(price)} ${currency}`;
  }
}

function productDisplayName(item: RecommendationItem): string {
  return item.product.displayNameKo || item.product.name;
}

function providerNameFromUrl(url?: string): string | undefined {
  if (!url) {
    return undefined;
  }
  try {
    const host = new URL(url).hostname.toLowerCase();
    const providers: Record<string, string> = {
      'world.openbeautyfacts.org': 'Open Beauty Facts',
      'www.oliveyoung.co.kr': '올리브영',
      'oliveyoung.co.kr': '올리브영',
      'www.ulta.com': 'Ulta Beauty',
      'ulta.com': 'Ulta Beauty',
      'glowpick.co.kr': '글로우픽',
      'www.glowpick.com': '글로우픽',
      'incidecoder.com': 'INCIDecoder',
      'dailymed.nlm.nih.gov': 'DailyMed',
      'fda.report': 'FDA.report',
    };
    return providers[host] ?? host.replace(/^www\./, '');
  } catch {
    return undefined;
  }
}

function productSourceNames(product: Product): string[] {
  const names = new Set<string>();
  if (product.catalogSource === 'open_beauty_facts') {
    names.add('Open Beauty Facts');
  } else if (product.catalogSource === 'curated') {
    names.add('검수된 큐레이션 데이터');
  } else if (product.catalogSource) {
    names.add(product.catalogSource.replace(/_/g, ' '));
  }
  product.externalLinks
    ?.filter((link) => link.kind === 'brand_official')
    .forEach((link) => names.add(link.provider));
  const sourceProvider = sourceUrlIsProductSource(product)
    ? providerNameFromUrl(product.sourceUrl)
    : undefined;
  if (sourceProvider) {
    names.add(sourceProvider);
  }
  return [...names];
}

function sourceLabel(item: RecommendationItem): string {
  const names = productSourceNames(item.product);
  return names.length ? `상품 출처 · ${names.join(' · ')}` : '상품 출처 · 확인 가능한 큐레이션 데이터';
}

function ingredientSourceNames(product: Product): string[] {
  return [...new Set(
    (product.externalLinks || [])
      .filter((link) => link.kind === 'ingredient_reference')
      .map((link) => link.provider),
  )];
}

function dataReferenceNames(product: Product): string[] {
  return [...new Set(
    (product.externalLinks || [])
      .filter((link) => link.kind === 'data_reference')
      .map((link) => link.provider),
  )];
}

function reviewSourceNames(product: Product): string[] {
  if (!product.reviewSourceUrl) {
    return [];
  }
  const verifiedProvider = product.externalLinks
    ?.find((link) => link.url === product.reviewSourceUrl)?.provider;
  return verifiedProvider ? [verifiedProvider] : [];
}

function informationLinkLabel(product: Product, link: ProductExternalLink): string {
  if (product.reviewSourceUrl === link.url) {
    return `리뷰 출처 · ${link.provider}`;
  }
  const prefix: Record<ProductExternalLink['kind'], string> = {
    brand_official: '공식 상품 정보',
    ingredient_reference: '성분 출처',
    data_reference: '데이터 출처',
    review_reference: '리뷰 출처',
  };
  return `${prefix[link.kind]} · ${link.provider}`;
}

function sourceDate(item: RecommendationItem): string {
  const value = item.dataConfidence?.factors.productSource?.checkedAt || item.product.sourceUpdatedAt;
  const date = value?.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  return date ? date.replace(/-/g, '.') : '';
}

function reviewDate(item: RecommendationItem): string {
  const value = item.dataConfidence?.factors.reviews?.checkedAt || item.product.reviewVerifiedAt;
  const date = value?.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  return date ? date.replace(/-/g, '.') : '';
}

function sourceAttributionUrl(product: Product): string | undefined {
  if (product.catalogSource !== 'open_beauty_facts') {
    return undefined;
  }
  for (const value of [product.sourceUrl, product.dataAttributionUrl]) {
    if (!value) {
      continue;
    }
    try {
      const parsed = new URL(value);
      if (parsed.protocol === 'https:' && parsed.hostname === 'world.openbeautyfacts.org') {
        return parsed.toString();
      }
    } catch {
      // Ignore malformed catalog metadata and use the canonical attribution URL.
    }
  }
  return OBF_DATA_URL;
}

function offerSummary(product: Product): { lowestPrice?: number; currency?: string; retailerCount: number } {
  const freshOffers = product.offers.filter(
    (offer) => !offer.isStale
      && offer.availability !== 'out_of_stock'
      && offer.currency === 'KRW'
      && offer.priceKrw !== undefined,
  );
  const lowestOffer = freshOffers.reduce<RetailOffer | undefined>(
    (lowest, offer) => (!lowest || (offer.priceKrw as number) < (lowest.priceKrw as number) ? offer : lowest),
    undefined,
  );
  return {
    lowestPrice: product.commerce?.lowestFreshPriceKrw ?? lowestOffer?.priceKrw,
    currency: product.commerce?.lowestFreshPriceCurrency ?? lowestOffer?.currency,
    retailerCount: product.commerce?.retailerCount
      ?? new Set(product.offers.map((offer) => offer.retailerId || offer.retailerName)).size,
  };
}

function toggleInList(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((item) => item !== value) : [...list, value];
}

function optionLabel(
  options: ReadonlyArray<{ value: string; label: string }>,
  value: string,
): string {
  return options.find((option) => option.value === value)?.label || value;
}

function selectedConditionLabels(answers: SurveyAnswers): string[] {
  const labels = [
    answers.skinType ? `피부 · ${optionLabel(SKIN_OPTIONS, answers.skinType)}` : '',
    answers.sensitivity ? `민감도 · ${optionLabel(SENSITIVITY_OPTIONS, answers.sensitivity)}` : '',
    answers.category ? `제품 · ${optionLabel(CATEGORY_OPTIONS, answers.category)}` : '',
    answers.primaryConcern ? `1순위 · ${optionLabel(CONCERN_OPTIONS, answers.primaryConcern)}` : '',
    ...answers.concerns.map((concern) => `추가 고민 · ${optionLabel(CONCERN_OPTIONS, concern)}`),
    answers.texture ? `제형 · ${optionLabel(TEXTURE_OPTIONS, answers.texture)}` : '',
    answers.finish ? `마무리 · ${optionLabel(FINISH_OPTIONS, answers.finish)}` : '',
    answers.budget ? `예산 · ${formatPrice(answers.budget)} 이하` : '예산 · 제한 없음',
  ];
  const avoided = [
    ...answers.avoidIngredients.map((ingredient) => optionLabel(AVOID_OPTIONS, ingredient)),
    ...answers.avoidIngredientsText.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
  ];
  const preferred = [
    ...answers.preferredIngredients.map((ingredient) => optionLabel(PREFERRED_OPTIONS, ingredient)),
    ...answers.preferredIngredientsText.split(/[,，]/).map((item) => item.trim()).filter(Boolean),
  ];
  if (avoided.length) {
    labels.push(`제외 · ${[...new Set(avoided)].join(', ')}`);
  }
  if (preferred.length) {
    labels.push(`선호 · ${[...new Set(preferred)].join(', ')}`);
  }
  return labels.filter(Boolean);
}

const DEVELOPER_TEXT_PATTERNS = [
  /\bchecked\b/i,
  /missing[_\s-]?data/i,
  /max[_\s-]?price/i,
  /excluded because/i,
  /cannot verify (?:under|over)/i,
  /가격 데이터가 없어 최대 가격 조건/i,
  /최대 가격 조건을 확인할 수 없음/i,
  /최소 가격 조건을 확인할 수 없음/i,
];

function isCustomerFacingText(value: string): boolean {
  const text = value.trim();
  return Boolean(text) && !DEVELOPER_TEXT_PATTERNS.some((pattern) => pattern.test(text));
}

function customerReasons(item: RecommendationItem): string[] {
  return [...new Set([...(item.reasons || []), item.reason])]
    .filter(isCustomerFacingText)
    .slice(0, 3);
}

function customerCaution(item: RecommendationItem): string | undefined {
  return item.cautions.find(isCustomerFacingText);
}

function matchLabel(_score?: number): string {
  return '조건 적합도 · 추천 기준 충족';
}

function evidenceLevelLabel(value: string): string {
  const labels: Record<string, string> = {
    high: '높음',
    moderate: '보통',
    low: '제한적',
    insufficient: '불충분',
  };
  return labels[value.toLowerCase()] || '확인 필요';
}

function hasMissingPrice(item: RecommendationItem): boolean {
  return item.missingData.some((value) => /price|가격/i.test(value));
}

function HeartIcon({ filled = false }: { filled?: boolean }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path
        d="M12 20.2S3.5 15.1 3.5 8.6A4.6 4.6 0 0 1 12 6.1a4.6 4.6 0 0 1 8.5 2.5c0 6.5-8.5 11.6-8.5 11.6Z"
        fill={filled ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="m9 5 7 7-7 7" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}

function SparkleIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 2c.6 5 3.4 7.8 8 8.5-4.6.8-7.4 3.6-8 8.5-.7-4.9-3.4-7.7-8-8.5C8.6 9.8 11.3 7 12 2Z" />
      <path d="M19.5 16c.2 1.7 1.2 2.7 2.5 3-1.3.2-2.3 1.2-2.5 3-.3-1.8-1.2-2.8-2.5-3 1.3-.3 2.2-1.3 2.5-3Z" />
    </svg>
  );
}

interface ChipGroupProps {
  options: ReadonlyArray<{ value: string; label: string }>;
  selected: string | string[];
  onSelect: (value: string) => void;
  multiple?: boolean;
  labelledBy?: string;
  describedBy?: string;
  invalid?: boolean;
}

function ChipGroup({
  options,
  selected,
  onSelect,
  multiple = false,
  labelledBy,
  describedBy,
  invalid,
}: ChipGroupProps) {
  const selectedValues = multiple ? (selected as string[]) : [selected as string];
  return (
    <div
      className="chip-group"
      role={labelledBy ? 'group' : undefined}
      aria-labelledby={labelledBy}
      aria-describedby={describedBy}
      aria-invalid={invalid || undefined}
    >
      {options.map((option) => {
        const active = selectedValues.includes(option.value);
        return (
          <button
            type="button"
            className={`chip ${active ? 'chip--selected' : ''}`}
            aria-pressed={active}
            key={option.value}
            onClick={() => onSelect(option.value)}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}

interface ProductCardProps {
  item: RecommendationItem;
  saved: boolean;
  onToggleSaved: (item: RecommendationItem) => void;
  onCompareOffers: (item: RecommendationItem) => void;
  onOpenInformation: (url: string) => void;
  compareSelected?: boolean;
  onToggleProductComparison?: (item: RecommendationItem) => void;
  compact?: boolean;
  priority?: boolean;
}

function ProductCard({
  item,
  saved,
  onToggleSaved,
  onCompareOffers,
  onOpenInformation,
  compareSelected = false,
  onToggleProductComparison,
  compact = false,
  priority = false,
}: ProductCardProps) {
  const { product } = item;
  const summary = offerSummary(product);
  const [imageFailed, setImageFailed] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const imageUrl = imageFailed ? undefined : product.imageUrl;
  const reasons = customerReasons(item);
  const caution = customerCaution(item);
  const fallbackAttributionUrl = sourceAttributionUrl(product);
  const informationLinks = product.externalLinks?.length
    ? product.externalLinks
    : fallbackAttributionUrl
      ? [{
          kind: 'data_reference' as const,
          label: '상품 정보 출처',
          provider: 'Open Beauty Facts',
          url: fallbackAttributionUrl,
        }]
      : [];
  const primaryInformationUrl = informationLinks[0]?.url;
  const canCompareRetailers = summary.retailerCount > 0 || product.catalogSource === 'curated';
  const canOpenInformation = !canCompareRetailers && Boolean(primaryInformationUrl);

  return (
    <article className={`product-card ${compact ? 'product-card--compact' : ''}`}>
      <div
        className={`product-image ${!imageUrl ? 'product-image--empty' : ''} ${imageUrl && !imageLoaded ? 'product-image--loading' : ''}`}
      >
        {imageUrl && (
          <img
            className={imageLoaded ? 'is-loaded' : ''}
            src={imageUrl}
            alt={`${productDisplayName(item)} 제품`}
            loading={priority ? 'eager' : 'lazy'}
            decoding="async"
            onLoad={() => setImageLoaded(true)}
            onError={() => {
              setImageFailed(true);
              setImageLoaded(false);
            }}
          />
        )}
        {(!imageUrl || !imageLoaded) && <span className="product-image-placeholder" aria-hidden="true">K</span>}
        <button
          type="button"
          className={`save-button ${saved ? 'save-button--active' : ''}`}
          aria-label={saved ? `${productDisplayName(item)} 찜 해제` : `${productDisplayName(item)} 찜하기`}
          aria-pressed={saved}
          onClick={() => onToggleSaved(item)}
        >
          <HeartIcon filled={saved} />
        </button>
      </div>

      <div className="product-content">
        <div className="product-heading">
          <div>
            <p className="product-brand">{product.brand}</p>
            <h3>{productDisplayName(item)}</h3>
          </div>
          <div className="product-commerce-summary">
            <strong className="product-price">
              {summary.lowestPrice !== undefined
                ? `최저 ${formatPrice(summary.lowestPrice, summary.currency)}`
                : canCompareRetailers ? '판매처에서 가격 확인' : '가격 정보 없음'}
            </strong>
            {summary.retailerCount > 0 && <span>판매처 {summary.retailerCount}곳</span>}
          </div>
        </div>

        {hasVerifiedReviewMetrics(product) && (
          <p className="rating-row">
            <span aria-hidden="true">★</span>
            {product.rating?.toFixed(1) || '리뷰'}
            {product.reviewCount ? ` · 리뷰 ${new Intl.NumberFormat('ko-KR').format(product.reviewCount)}개` : ''}
          </p>
        )}

        {!compact && (
          <div className="fit-confidence-row" aria-label="맞춤도와 데이터 신뢰도">
            <span className="match-badge">{matchLabel(item.score)}</span>
            {item.dataConfidence ? (
              <details className={`confidence-details confidence-details--${item.dataConfidence.level}`}>
                <summary>데이터 신뢰도 · {item.dataConfidence.labelKo.replace(/^근거\s*신뢰도\s*/, '')}</summary>
                <ul>
                  {[
                    item.dataConfidence.factors.ingredients,
                    item.dataConfidence.factors.productSource,
                    item.dataConfidence.factors.reviews,
                  ].map((factor, index) => factor ? (
                    <li key={`${factor.status}:${factor.labelKo}:${index}`}>
                      {factor.labelKo}
                      {factor.checkedAt ? ` · ${formatCheckedAt(factor.checkedAt)}` : ''}
                    </li>
                  ) : null)}
                </ul>
              </details>
            ) : (
              <span className="confidence-badge">데이터 신뢰도 · 확인 중</span>
            )}
          </div>
        )}

        <div className="source-row">
          <span>{sourceLabel(item)}</span>
          {ingredientSourceNames(product).length > 0 && (
            <span>성분 출처 · {ingredientSourceNames(product).join(' · ')}</span>
          )}
          {dataReferenceNames(product).length > 0 && (
            <span>데이터 출처 · {dataReferenceNames(product).join(' · ')}</span>
          )}
          {sourceDate(item) && <span>상품 정보 확인 {sourceDate(item)}</span>}
          {informationLinks.map((link) => (
            <button
              type="button"
              key={`${link.kind}:${link.url}`}
              onClick={() => onOpenInformation(link.url)}
            >
              {informationLinkLabel(product, link)}
            </button>
          ))}
          {reviewDate(item) && <span>리뷰 확인 {reviewDate(item)}</span>}
        </div>

        {!compact && (
          <>
            <section className="reason-box" aria-label="추천 이유">
              <span className="reason-icon">
                <SparkleIcon />
              </span>
              <div>
                <strong>이 제품을 고른 이유</strong>
                {reasons.length > 0 ? (
                  <ul>
                    {reasons.map((reason) => <li key={reason}>{reason}</li>)}
                  </ul>
                ) : (
                  <p>선택한 피부 조건과 제품 정보를 함께 비교해 고른 후보예요.</p>
                )}
              </div>
            </section>

            {item.matchedIngredients.length > 0 && (
              <div className="ingredient-row" aria-label="주요 성분">
                {item.matchedIngredients.slice(0, 4).map((ingredient) => (
                  <span key={ingredient}>{ingredient}</span>
                ))}
              </div>
            )}

            {product.ingredientExplanations.length > 0 && (
              <details className="ingredient-evidence-details">
                <summary>성분 근거 자세히 보기 <span>{product.ingredientExplanations.length}</span></summary>
                <div className="ingredient-evidence-list">
                  {product.ingredientExplanations.slice(0, 8).map((explanation) => {
                    const supports = explanation.displaySupportsKo.length
                      ? explanation.displaySupportsKo
                      : explanation.supports;
                    const cautions = explanation.displayCautionsKo.length
                      ? explanation.displayCautionsKo
                      : explanation.cautions;
                    return (
                      <article key={explanation.name}>
                        <h4>{explanation.displayNameKo || explanation.label || explanation.name}</h4>
                        {supports.length > 0 && <p><strong>도움 가능</strong> {supports.join(', ')}</p>}
                        {cautions.length > 0 && <p><strong>주의</strong> {cautions.join(', ')}</p>}
                        {(explanation.displayRationaleKo || explanation.rationale) && (
                          <p>{explanation.displayRationaleKo || explanation.rationale}</p>
                        )}
                        {explanation.evidenceLevel && (
                          <small>근거 수준 · {evidenceLevelLabel(explanation.evidenceLevel)}</small>
                        )}
                      </article>
                    );
                  })}
                </div>
              </details>
            )}

            {caution && (
              <p className="caution-row">
                <strong>확인해 주세요</strong> {caution}
              </p>
            )}
          </>
        )}

        {onToggleProductComparison && (
          <button
            type="button"
            className={`compare-toggle ${compareSelected ? 'compare-toggle--selected' : ''}`}
            aria-pressed={compareSelected}
            aria-label={compareSelected
              ? `${productDisplayName(item)} 비교에서 빼기`
              : `${productDisplayName(item)} 비교에 담기`}
            onClick={() => onToggleProductComparison(item)}
          >
            <span aria-hidden="true">{compareSelected ? '✓' : '+'}</span>
            {compareSelected ? '비교에 담았어요' : '제품 비교에 담기'}
          </button>
        )}

        <button
          type="button"
          className="purchase-button"
          disabled={!canCompareRetailers && !canOpenInformation}
          onClick={() => {
            if (canCompareRetailers) {
              onCompareOffers(item);
            } else if (primaryInformationUrl) {
              onOpenInformation(primaryInformationUrl);
            }
          }}
        >
          {summary.retailerCount > 0
            ? `판매처 ${summary.retailerCount}곳 비교`
            : canOpenInformation ? '제품 정보 보기' : canCompareRetailers ? '판매처 확인' : '판매처 준비 중'}
          <ArrowIcon />
        </button>
      </div>
    </article>
  );
}

function formatCheckedAt(value?: string): string {
  if (!value) {
    return '확인 시각 미제공';
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return `${new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)} 확인`;
}

function availabilityLabel(offer: RetailOffer): string {
  if (offer.availability === 'in_stock') {
    return '재고 있음';
  }
  if (offer.availability === 'preorder') {
    return '예약 판매';
  }
  if (offer.availability === 'out_of_stock') {
    return '품절';
  }
  return '재고 확인 필요';
}

interface OfferComparisonDialogProps {
  item: RecommendationItem;
  offers: RetailOffer[];
  loading: boolean;
  error: string;
  onRetry: () => void;
  onClose: () => void;
  onOpenError: (message: string) => void;
}

function OfferComparisonDialog({
  item,
  offers,
  loading,
  error,
  onRetry,
  onClose,
  onOpenError,
}: OfferComparisonDialogProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);
  const sortedOffers = useMemo(() => [...offers].sort((left, right) => {
    const leftRank = left.isStale || left.availability === 'out_of_stock' ? 1 : 0;
    const rightRank = right.isStale || right.availability === 'out_of_stock' ? 1 : 0;
    if (leftRank !== rightRank) {
      return leftRank - rightRank;
    }
    const currencyRank = (left.currency === 'KRW' ? 0 : 1) - (right.currency === 'KRW' ? 0 : 1);
    if (currencyRank !== 0) {
      return currencyRank;
    }
    if (left.currency === right.currency) {
      return (left.priceAmount ?? Number.MAX_SAFE_INTEGER) - (right.priceAmount ?? Number.MAX_SAFE_INTEGER);
    }
    return left.retailerName.localeCompare(right.retailerName);
  }), [offers]);

  useEffect(() => {
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';
    const dialog = dialogRef.current;
    dialog?.querySelector<HTMLButtonElement>('.offer-dialog-close')?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === 'Escape') {
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== 'Tab' || !dialog) {
        return;
      }
      const focusable = Array.from(dialog.querySelectorAll<HTMLElement>(
        'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ));
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    }

    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, []);

  return (
    <div
      className="offer-dialog-layer"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <section
        className="offer-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="offer-dialog-title"
        aria-describedby="offer-dialog-description"
        ref={dialogRef}
      >
        <div className="offer-dialog-handle" aria-hidden="true" />
        <header className="offer-dialog-header">
          <div>
            <p>{item.product.brand}</p>
            <h2 id="offer-dialog-title">판매처 비교</h2>
          </div>
          <button type="button" className="offer-dialog-close" onClick={onClose} aria-label="판매처 비교 닫기">
            ×
          </button>
        </header>
        <p id="offer-dialog-description" className="offer-dialog-product-name">{productDisplayName(item)}</p>
        <p className="external-transition-notice">구매 버튼을 누르면 토스를 벗어나 판매처 웹사이트로 이동해요. 실제 가격과 재고를 다시 확인해 주세요.</p>

        {loading && offers.length === 0 ? (
          <div className="offer-loading" role="status">최신 가격과 재고를 확인하고 있어요.</div>
        ) : error && offers.length === 0 ? (
          <div className="offer-error" role="alert">
            <p>{error}</p>
            <button type="button" onClick={onRetry}>다시 불러오기</button>
          </div>
        ) : sortedOffers.length > 0 ? (
          <div className="offer-list">
            {sortedOffers.map((offer) => (
              <article className="offer-row" key={offer.id}>
                <div className="offer-row-heading">
                  <div>
                    <strong>{offer.retailerName}</strong>
                    {offer.isAffiliate && (
                      <span className="affiliate-badge">{offer.affiliateLabel || '광고·제휴'}</span>
                    )}
                  </div>
                  <div className="offer-price-block">
                    {offer.listPriceAmount !== undefined && offer.priceAmount !== undefined && offer.listPriceAmount > offer.priceAmount && (
                      <del>{formatPrice(offer.listPriceAmount, offer.currency)}</del>
                    )}
                    <strong>
                      {offer.priceAmount !== undefined
                        ? formatPrice(offer.priceAmount, offer.currency)
                        : '판매처에서 가격 확인'}
                    </strong>
                  </div>
                </div>
                <div className="offer-meta">
                  {offer.isLinkOnly ? (
                    <>
                      <span className="availability availability--unknown">판매처에서 확인</span>
                      <span>가격·재고는 판매처의 최신 정보를 확인해 주세요.</span>
                    </>
                  ) : (
                    <>
                      <span className={`availability availability--${offer.availability}`}>{availabilityLabel(offer)}</span>
                      {offer.isStale && <span className="stale-badge">정보 업데이트 필요</span>}
                      <span>{formatCheckedAt(offer.checkedAt)}</span>
                    </>
                  )}
                </div>
                {offer.isAffiliate && (
                  <p className="affiliate-disclosure">
                    {offer.affiliateDisclosure || '이 링크를 통해 구매하면 판매처로부터 수수료를 받을 수 있어요.'}
                  </p>
                )}
                <button
                  type="button"
                  className="offer-open-button"
                  disabled={!offer.clickUrl}
                  onClick={() => {
                    if (!offer.clickUrl) {
                      return;
                    }
                    void openExternalUrl(offer.clickUrl).catch((openError: unknown) => {
                      onOpenError(openError instanceof Error ? openError.message : '판매처 페이지를 열지 못했어요.');
                    });
                  }}
                >
                  {offer.clickUrl
                    ? offer.isLinkOnly ? `${offer.retailerName}에서 보기` : '판매처에서 확인'
                    : '구매 링크 준비 중'}
                  {offer.clickUrl && <ArrowIcon />}
                </button>
              </article>
            ))}
          </div>
        ) : (
          <div className="offer-empty" role="status">아직 연결된 판매처가 없어요. 제품 정보 보기에서 상세 정보를 확인해 주세요.</div>
        )}

        {loading && offers.length > 0 && <p className="offer-refreshing" role="status">최신 정보를 확인 중이에요.</p>}
        {error && offers.length > 0 && <p className="offer-refreshing" role="status">{error}</p>}
      </section>
    </div>
  );
}

function LoadingPanel() {
  return (
    <div className="loading-panel" role="status" aria-live="polite">
      <div className="loading-orbit" aria-hidden="true">
        <span />
      </div>
      <h2>딱 맞는 제품을 찾고 있어요</h2>
      <p>여러 상품의 성분과 피부 적합도를 비교하고 있어요.</p>
      <div className="loading-steps" aria-hidden="true">
        <span className="is-active" />
        <span />
        <span />
      </div>
    </div>
  );
}

function App() {
  const safeArea = useSafeAreaInsets();
  const initialSavedState = useRef<ReturnType<typeof readSavedState> | null>(null);
  if (initialSavedState.current === null) {
    initialSavedState.current = readSavedState();
  }
  const [screen, setScreen] = useState<Screen>('survey');
  const [answers, setAnswers] = useState<SurveyAnswers>(INITIAL_ANSWERS);
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [savedProductIds, setSavedProductIds] = useState<string[]>(initialSavedState.current.ids);
  const [savedItemCache, setSavedItemCache] = useState<Record<string, RecommendationItem>>(
    initialSavedState.current.cache,
  );
  const [compareProductIds, setCompareProductIds] = useState<string[]>([]);
  const [offerDialog, setOfferDialog] = useState<{
    item: RecommendationItem;
    offers: RetailOffer[];
    loading: boolean;
    error: string;
  } | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState('');
  const [toast, setToast] = useState('');
  const toastTimer = useRef<number | undefined>(undefined);
  const screenStack = useRef<Screen[]>(['survey']);
  const offerDialogTrigger = useRef<HTMLElement | null>(null);
  const skinQuestionRef = useRef<HTMLElement | null>(null);
  const sensitivityQuestionRef = useRef<HTMLElement | null>(null);
  const categoryQuestionRef = useRef<HTMLElement | null>(null);
  const primaryConcernRef = useRef<HTMLElement | null>(null);
  const ingredientQuestionRef = useRef<HTMLElement | null>(null);
  const privacyConsentRef = useRef<HTMLInputElement | null>(null);

  const savedIds = useMemo(() => new Set(savedProductIds), [savedProductIds]);
  const compareIds = useMemo(() => new Set(compareProductIds), [compareProductIds]);
  const allResultItems = useMemo(() => {
    const items = [...(result?.items || []), ...(result?.additionalCandidates || [])];
    return [...new Map(items.map((item) => [item.product.id, item])).values()];
  }, [result]);
  const currentItems = useMemo(
    () => new Map(allResultItems.map((item) => [item.product.id, item])),
    [allResultItems],
  );
  const compareItems = useMemo(
    () => compareProductIds
      .map((id) => currentItems.get(id))
      .filter((item): item is RecommendationItem => Boolean(item)),
    [compareProductIds, currentItems],
  );
  const savedItems = useMemo(
    () => savedProductIds
      .map((id) => currentItems.get(id) || savedItemCache[id] || savedItemPlaceholder(id)),
    [currentItems, savedItemCache, savedProductIds],
  );
  const selectionConflicts = useMemo(() => ingredientSelectionConflicts(answers), [answers]);
  const conditionLabels = useMemo(() => selectedConditionLabels(answers), [answers]);
  const unpricedResultItems = useMemo(() => {
    const candidates = [
      ...(result?.additionalCandidates || []),
      ...(answers.budget ? (result?.items || []).filter(hasMissingPrice) : []),
    ];
    return [...new Map(candidates.map((item) => [item.product.id, item])).values()];
  }, [answers.budget, result]);
  const pricedResultItems = useMemo(() => {
    const additionalIds = new Set(unpricedResultItems.map((item) => item.product.id));
    return (result?.items || []).filter((item) => (
      !additionalIds.has(item.product.id) && (!answers.budget || !hasMissingPrice(item))
    ));
  }, [answers.budget, result, unpricedResultItems]);
  const announcedItemCount = screen === 'results'
    ? allResultItems.length
    : screen === 'compare'
      ? compareItems.length
      : screen === 'saved'
        ? savedItems.length
        : 0;

  useEffect(() => {
    try {
      const storageKeys = [
        LEGACY_SAVED_STORAGE_KEY,
        SAVED_IDS_STORAGE_KEY,
        SAVED_CACHE_STORAGE_KEY,
        SAVED_ISSUED_AT_KEY,
      ];
      if (savedProductIds.length === 0) {
        const hasStoredSavedData = storageKeys.some((key) => window.localStorage.getItem(key) !== null);
        if (hasStoredSavedData) {
          storageKeys.forEach((key) => window.localStorage.removeItem(key));
        }
        return;
      }
      const cache = Object.fromEntries(
        savedProductIds
          .map((id) => [id, savedItemCache[id]] as const)
          .filter((entry): entry is readonly [string, RecommendationItem] => Boolean(entry[1])),
      );
      window.localStorage.removeItem(LEGACY_SAVED_STORAGE_KEY);
      window.localStorage.setItem(SAVED_IDS_STORAGE_KEY, JSON.stringify(savedProductIds));
      window.localStorage.setItem(SAVED_CACHE_STORAGE_KEY, JSON.stringify(cache));
      window.localStorage.setItem(SAVED_ISSUED_AT_KEY, String(Date.now()));
    } catch {
      // 저장 공간이 제한된 환경에서도 현재 세션의 찜 기능은 유지합니다.
    }
  }, [savedItemCache, savedProductIds]);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  useEffect(() => {
    if (!offerDialog && screenStack.current.length <= 1) {
      return undefined;
    }

    try {
      return graniteEvent.addEventListener('backEvent', {
        onEvent: () => {
          if (offerDialog) {
            closeOfferDialog();
          } else {
            goBack();
          }
        },
        onError: () => undefined,
      });
    } catch {
      return undefined;
    }
  }, [screen, offerDialog]);

  const appStyle = {
    '--safe-top': `${safeArea.top}px`,
    '--safe-right': `${safeArea.right}px`,
    '--safe-bottom': `${safeArea.bottom}px`,
    '--safe-left': `${safeArea.left}px`,
  } as CSSProperties;

  function navigate(next: Screen) {
    if (screenStack.current[screenStack.current.length - 1] === next) {
      return;
    }
    screenStack.current = [...screenStack.current, next];
    setScreen(next);
    setError('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function goBack() {
    if (screenStack.current.length <= 1) {
      return;
    }

    const nextStack = screenStack.current.slice(0, -1);
    screenStack.current = nextStack;
    setScreen(nextStack[nextStack.length - 1] ?? 'survey');
    setError('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function goHome() {
    screenStack.current = ['survey'];
    setScreen('survey');
    setError('');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  function showToast(message: string) {
    setToast(message);
    window.clearTimeout(toastTimer.current);
    toastTimer.current = window.setTimeout(() => setToast(''), 2_200);
  }

  function toggleSaved(item: RecommendationItem) {
    const alreadySaved = savedIds.has(item.product.id);
    setSavedProductIds((current) =>
      alreadySaved
        ? current.filter((id) => id !== item.product.id)
        : [item.product.id, ...current.filter((id) => id !== item.product.id)],
    );
    setSavedItemCache((current) => {
      const next = { ...current };
      if (alreadySaved) {
        delete next[item.product.id];
      } else {
        next[item.product.id] = withoutDynamicOfferData(item);
      }
      return next;
    });
    showToast(alreadySaved ? '찜 목록에서 삭제했어요.' : '찜 목록에 저장했어요.');
  }

  function toggleProductComparison(item: RecommendationItem) {
    const productId = item.product.id;
    if (compareIds.has(productId)) {
      setCompareProductIds((current) => current.filter((id) => id !== productId));
      showToast('비교 목록에서 뺐어요.');
      return;
    }
    if (compareProductIds.length >= 5) {
      showToast('제품 비교는 최대 5개까지 가능해요.');
      return;
    }
    setCompareProductIds((current) => [...current, productId]);
    showToast('비교 목록에 담았어요.');
  }

  async function deleteAllData() {
    const deletionPromise = deleteUserData(
      deleteAnonymousSessionData,
      window.localStorage,
      [
        LEGACY_SAVED_STORAGE_KEY,
        SAVED_IDS_STORAGE_KEY,
        SAVED_CACHE_STORAGE_KEY,
        SAVED_ISSUED_AT_KEY,
      ],
    );
    // Device keys are removed synchronously before the remote request is
    // awaited, so reset the visible state immediately on a slow network.
    setSavedProductIds([]);
    setSavedItemCache({});
    setCompareProductIds([]);
    setResult(null);
    setAnswers(INITIAL_ANSWERS);
    setError('');
    setValidation('');
    goHome();

    const deletion = await deletionPromise;

    if (deletion.serverDeleted && deletion.deviceCleared) {
      showToast('서버와 기기에 저장된 내 데이터를 삭제했어요.');
    } else if (!deletion.serverDeleted && deletion.deviceCleared) {
      showToast('기기 데이터는 삭제했어요. 서버 삭제는 네트워크가 안정되면 다시 시도해 주세요.');
    } else {
      showToast('일부 데이터를 지우지 못했어요. 잠시 후 다시 시도해 주세요.');
    }
  }

  function openPrivacyNotice() {
    void openExternalUrl(privacyPolicyUrl()).catch((openError: unknown) => {
      showToast(openError instanceof Error ? openError.message : '개인정보 처리 안내를 열지 못했어요.');
    });
  }

  function openInformationUrl(url: string) {
    void openExternalUrl(url).catch((openError: unknown) => {
      showToast(openError instanceof Error ? openError.message : '외부 정보 페이지를 열지 못했어요.');
    });
  }

  function closeOfferDialog() {
    setOfferDialog(null);
    window.requestAnimationFrame(() => offerDialogTrigger.current?.focus());
  }

  async function refreshOffers(item: RecommendationItem) {
    const productId = item.product.id;
    setOfferDialog((current) => current && current.item.product.id === productId
      ? { ...current, loading: true, error: '' }
      : current);
    try {
      const offers = await requestProductOffers(productId);
      setOfferDialog((current) => current && current.item.product.id === productId
        ? { ...current, offers, loading: false, error: '' }
        : current);
    } catch (offerError) {
      const message = offerError instanceof Error ? offerError.message : '판매처 정보를 불러오지 못했어요.';
      setOfferDialog((current) => current && current.item.product.id === productId
        ? { ...current, loading: false, error: message }
        : current);
    }
  }

  function openOfferComparison(item: RecommendationItem) {
    offerDialogTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const hasLegacyOffer = !item.product.commerce && item.product.offers.length > 0;
    setOfferDialog({ item, offers: item.product.offers, loading: !hasLegacyOffer, error: '' });
    if (hasLegacyOffer) {
      return;
    }
    void refreshOffers(item);
  }

  function selectPrimaryConcern(value: string) {
    setAnswers((current) => ({
      ...current,
      primaryConcern: value,
      concerns: current.concerns.filter((concern) => concern !== value),
    }));
  }

  function toggleAdditionalConcern(value: string) {
    setAnswers((current) => {
      if (current.concerns.includes(value)) {
        return { ...current, concerns: current.concerns.filter((concern) => concern !== value) };
      }
      if (current.concerns.length >= 2) {
        showToast('추가 고민은 최대 2개까지 선택할 수 있어요.');
        return current;
      }
      return { ...current, concerns: [...current.concerns, value] };
    });
  }

  async function runRecommendation() {
    const requiredQuestions = [
      { missing: !answers.skinType, label: '피부 타입', element: skinQuestionRef.current },
      { missing: !answers.sensitivity, label: '민감도', element: sensitivityQuestionRef.current },
      { missing: !answers.category, label: '찾는 제품', element: categoryQuestionRef.current },
      { missing: !answers.primaryConcern, label: '1순위 피부 고민', element: primaryConcernRef.current },
    ];
    const firstMissing = requiredQuestions.find((question) => question.missing);
    if (firstMissing) {
      const missingLabels = requiredQuestions.filter((question) => question.missing).map((question) => question.label);
      setValidation(`선택이 필요한 항목: ${missingLabels.join(', ')}`);

      const question = firstMissing.element;
      const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
      question?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'center' });
      window.requestAnimationFrame(() => {
        question?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
      });
      return;
    }

    if (selectionConflicts.length > 0) {
      setValidation(`제외 성분과 선호 성분에 함께 선택된 항목을 정리해 주세요: ${selectionConflicts.join(', ')}`);
      const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
      ingredientQuestionRef.current?.scrollIntoView({
        behavior: prefersReducedMotion ? 'auto' : 'smooth',
        block: 'center',
      });
      window.requestAnimationFrame(() => {
        ingredientQuestionRef.current?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
      });
      return;
    }

    setValidation('');
    setError('');
    setLoading(true);
    try {
      const nextResult = await requestRecommendations(answers);
      setCompareProductIds([]);
      setResult(nextResult);
      navigate('results');
    } catch (requestError) {
      setError(requestError instanceof Error ? requestError.message : '추천을 불러오지 못했어요.');
    } finally {
      setLoading(false);
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runRecommendation();
  }

  return (
    <div className="app-shell" style={appStyle}>
      <div className="sr-only" role="status" aria-live="polite" aria-atomic="true">
        {routeAnnouncement(screen, loading, announcedItemCount)}
      </div>
      <header className="app-header">
        <button type="button" className="brand-button" onClick={goHome} aria-label="추천 설문 홈">
          <span className="brand-mark">K</span>
          <span>K뷰티에이전트</span>
        </button>
        <button type="button" className="saved-link" onClick={() => navigate('saved')} aria-label={`찜 목록 ${savedItems.length}개`}>
          <HeartIcon filled={screen === 'saved'} />
          {savedItems.length > 0 && <span>{savedItems.length}</span>}
        </button>
      </header>

      <main>
        {loading ? (
          <LoadingPanel />
        ) : screen === 'survey' ? (
          <div className="survey-screen">
            <section className="hero-section">
              <span className="eyebrow">K-뷰티부터 글로벌 스킨케어까지</span>
              <h1>
                내 피부에 맞는 제품,
                <br />
                근거까지 보고 골라요
              </h1>
              <p>몇 가지만 알려주면 여러 출처의 제품 성분과 피부 적합도를 비교해 드려요.</p>
              <div className="hero-visual" aria-hidden="true">
                <div className="hero-bottle hero-bottle--left"><span /></div>
                <div className="hero-jar"><span>K</span></div>
                <div className="hero-bottle hero-bottle--right"><span /></div>
                <i className="sparkle sparkle--one">✦</i>
                <i className="sparkle sparkle--two">✧</i>
              </div>
            </section>

            <form className="survey-form" onSubmit={handleSubmit}>
              <section className="question-section" ref={skinQuestionRef}>
                <div className="question-title">
                  <span>1</span>
                  <div>
                    <h2 id={SKIN_QUESTION_TITLE_ID}>피부 타입이 어떻게 되나요?</h2>
                    <p>세안 후 피부 전체의 느낌과 가장 가까운 하나를 골라주세요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={SKIN_OPTIONS}
                  selected={answers.skinType}
                  labelledBy={SKIN_QUESTION_TITLE_ID}
                  describedBy={validation && !answers.skinType ? VALIDATION_MESSAGE_ID : undefined}
                  invalid={Boolean(validation && !answers.skinType)}
                  onSelect={(value) => setAnswers((current) => ({ ...current, skinType: value as SurveyAnswers['skinType'] }))}
                />
              </section>

              <section className="question-section" ref={sensitivityQuestionRef}>
                <div className="question-title">
                  <span>2</span>
                  <div>
                    <h2 id={SENSITIVITY_QUESTION_TITLE_ID}>피부 민감도는 어느 정도인가요?</h2>
                    <p>피부 타입과 별개로, 제품을 바꿨을 때 따가움이나 붉어짐을 기준으로 골라주세요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={SENSITIVITY_OPTIONS}
                  selected={answers.sensitivity}
                  labelledBy={SENSITIVITY_QUESTION_TITLE_ID}
                  describedBy={validation && !answers.sensitivity ? VALIDATION_MESSAGE_ID : undefined}
                  invalid={Boolean(validation && !answers.sensitivity)}
                  onSelect={(value) => setAnswers((current) => ({
                    ...current,
                    sensitivity: value as SurveyAnswers['sensitivity'],
                  }))}
                />
              </section>

              <section className="question-section" ref={categoryQuestionRef}>
                <div className="question-title">
                  <span>3</span>
                  <div>
                    <h2 id={CATEGORY_QUESTION_TITLE_ID}>어떤 제품을 찾고 있나요?</h2>
                    <p>이번에 가장 필요한 제품을 선택해 주세요.</p>
                  </div>
                </div>
                <div
                  className="category-grid"
                  role="group"
                  aria-labelledby={CATEGORY_QUESTION_TITLE_ID}
                  aria-describedby={validation && !answers.category ? VALIDATION_MESSAGE_ID : undefined}
                  aria-invalid={Boolean(validation && !answers.category) || undefined}
                >
                  {CATEGORY_OPTIONS.map((option) => {
                    const active = answers.category === option.value;
                    return (
                      <button
                        type="button"
                        key={option.value}
                        className={active ? 'is-selected' : ''}
                        aria-pressed={active}
                        onClick={() => setAnswers((current) => ({ ...current, category: option.value }))}
                      >
                        <span aria-hidden="true">{option.icon}</span>
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="question-section" ref={primaryConcernRef}>
                <div className="question-title">
                  <span>4</span>
                  <div>
                    <h2 id={PRIMARY_CONCERN_TITLE_ID}>가장 먼저 해결하고 싶은 고민은요?</h2>
                    <p>1순위는 꼭 하나, 추가 고민은 최대 2개까지 선택할 수 있어요.</p>
                  </div>
                </div>
                <div className="concern-group">
                  <strong>1순위 고민 <span>필수</span></strong>
                  <ChipGroup
                    options={CONCERN_OPTIONS}
                    selected={answers.primaryConcern}
                    labelledBy={PRIMARY_CONCERN_TITLE_ID}
                    describedBy={validation && !answers.primaryConcern ? VALIDATION_MESSAGE_ID : undefined}
                    invalid={Boolean(validation && !answers.primaryConcern)}
                    onSelect={selectPrimaryConcern}
                  />
                </div>
                <div className="concern-group concern-group--secondary">
                  <strong>추가 고민 <span>{answers.concerns.length}/2</span></strong>
                  <ChipGroup
                    options={CONCERN_OPTIONS.filter((option) => option.value !== answers.primaryConcern)}
                    selected={answers.concerns}
                    multiple
                    onSelect={toggleAdditionalConcern}
                  />
                </div>
              </section>

              <section className="question-section">
                <div className="question-title">
                  <span>5</span>
                  <div>
                    <h2>선호하는 제형이 있나요?</h2>
                    <p>제품을 덜어냈을 때의 질감이에요. 건너뛰어도 괜찮아요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={TEXTURE_OPTIONS}
                  selected={answers.texture}
                  onSelect={(value) => setAnswers((current) => ({
                    ...current,
                    texture: current.texture === value ? '' : value,
                  }))}
                />
              </section>

              <section className="question-section">
                <div className="question-title">
                  <span>6</span>
                  <div>
                    <h2>선호하는 마무리감이 있나요?</h2>
                    <p>바른 뒤 피부에 남는 느낌이에요. 제형과 따로 비교해요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={FINISH_OPTIONS}
                  selected={answers.finish}
                  onSelect={(value) => setAnswers((current) => ({
                    ...current,
                    finish: current.finish === value ? '' : value,
                  }))}
                />
              </section>

              <section className="question-section">
                <div className="question-title">
                  <span>7</span>
                  <div>
                    <h2>예산은 어느 정도인가요?</h2>
                    <p>예산을 고르면 가격을 확인할 수 없는 제품은 별도 후보로 보여드려요.</p>
                  </div>
                </div>
                <div className="chip-group">
                  {BUDGET_OPTIONS.map((option) => {
                    const active = answers.budget === option.value;
                    return (
                      <button
                        type="button"
                        key={option.label}
                        className={`chip ${active ? 'chip--selected' : ''}`}
                        aria-pressed={active}
                        onClick={() => setAnswers((current) => ({ ...current, budget: option.value }))}
                      >
                        {option.label}
                      </button>
                    );
                  })}
                </div>
              </section>

              <section className="question-section question-section--last" ref={ingredientQuestionRef}>
                <div className="question-title">
                  <span>8</span>
                  <div>
                    <h2 id={INGREDIENT_QUESTION_TITLE_ID}>성분 조건이 있나요?</h2>
                    <p>제외 성분은 후보에서 빼고, 선호 성분은 있으면 순위에만 반영해요.</p>
                  </div>
                </div>
                <div className="ingredient-preference-grid" aria-labelledby={INGREDIENT_QUESTION_TITLE_ID}>
                  <section className="ingredient-preference ingredient-preference--avoid">
                    <div className="ingredient-preference-heading">
                      <h3>제외 성분</h3>
                      <span>반드시 제외</span>
                    </div>
                    <p>선택한 성분이 확인되면 추천 후보에서 제외해요.</p>
                    <ChipGroup
                      options={AVOID_OPTIONS}
                      selected={answers.avoidIngredients}
                      multiple
                      onSelect={(value) => setAnswers((current) => ({
                        ...current,
                        avoidIngredients: toggleInList(current.avoidIngredients, value),
                      }))}
                    />
                    <label className="text-field">
                      <span>제외 성분 직접 입력</span>
                      <input
                        type="text"
                        value={answers.avoidIngredientsText}
                        maxLength={120}
                        placeholder="쉼표로 구분해 주세요"
                        onChange={(event) => setAnswers((current) => ({
                          ...current,
                          avoidIngredientsText: event.target.value,
                        }))}
                      />
                    </label>
                  </section>

                  <section className="ingredient-preference ingredient-preference--prefer">
                    <div className="ingredient-preference-heading">
                      <h3>선호 성분</h3>
                      <span>있으면 우선</span>
                    </div>
                    <p>없어도 제외하지 않고, 포함된 제품을 더 높은 순위로 보여줘요.</p>
                    <ChipGroup
                      options={PREFERRED_OPTIONS}
                      selected={answers.preferredIngredients}
                      multiple
                      onSelect={(value) => setAnswers((current) => ({
                        ...current,
                        preferredIngredients: toggleInList(current.preferredIngredients, value),
                      }))}
                    />
                    <label className="text-field">
                      <span>선호 성분 직접 입력</span>
                      <input
                        type="text"
                        value={answers.preferredIngredientsText}
                        maxLength={120}
                        placeholder="쉼표로 구분해 주세요"
                        onChange={(event) => setAnswers((current) => ({
                          ...current,
                          preferredIngredientsText: event.target.value,
                        }))}
                      />
                    </label>
                  </section>
                </div>
                {selectionConflicts.length > 0 && (
                  <p className="ingredient-conflict" role="alert">
                    <strong>선택이 겹쳐요.</strong> {selectionConflicts.join(', ')} 성분이 제외와 선호에 모두 있어요. 한쪽 선택을 해제해 주세요.
                  </p>
                )}
                <p className="health-data-note">알레르기·임신·수유 같은 건강정보는 입력하지 말고, 성분명만 적어 주세요.</p>
              </section>

              {validation && (
                <p id={VALIDATION_MESSAGE_ID} className="form-message form-message--validation" role="alert">
                  {validation}
                </p>
              )}
              {error && (
                <div className="error-panel" role="alert">
                  <div>
                    <strong>추천을 불러오지 못했어요</strong>
                    <p>{error}</p>
                  </div>
                  <button type="button" onClick={() => void runRecommendation()}>다시 시도</button>
                </div>
              )}

              <div className="privacy-consent">
                <label>
                  <input
                    ref={privacyConsentRef}
                    type="checkbox"
                    checked={answers.privacyConsent}
                    onChange={(event) => setAnswers((current) => ({
                      ...current,
                      privacyConsent: event.target.checked,
                    }))}
                  />
                  <span><strong>선택 동의</strong> · 동의하면 피부 정보와 성분 선호를 맞춤 재추천에 사용하고 최대 30일 보관해요. 동의하지 않아도 이번 1회 추천은 가능해요.</span>
                </label>
                <button type="button" onClick={openPrivacyNotice}>개인정보 처리 안내</button>
              </div>

              <button type="submit" className="primary-button">
                내 피부 맞춤 제품 찾기
                <ArrowIcon />
              </button>
              <p className="privacy-note">동의하지 않은 설문 정보는 재추천용으로 보관하지 않아요. 저장된 정보는 언제든 아래에서 삭제할 수 있어요.</p>
            </form>
          </div>
        ) : screen === 'results' ? (
          <div className="results-screen">
            <section className="results-heading">
              <span className="eyebrow">맞춤 분석 완료</span>
              <h1>{allResultItems.length}개 제품을 골랐어요</h1>
              <p>{result?.summary && isCustomerFacingText(result.summary)
                ? result.summary
                : '선택한 피부 조건과 확인 가능한 제품 근거를 함께 비교했어요.'}</p>
            </section>

            <section className="condition-summary" aria-label="선택한 추천 조건">
              <div className="condition-summary-heading">
                <strong>선택한 조건</strong>
                <button type="button" onClick={goHome}>조건 수정</button>
              </div>
              <div className="condition-chip-list">
                {conditionLabels.map((label) => <span key={label}>{label}</span>)}
              </div>
            </section>

            {result?.rankingPolicy && isCustomerFacingText(result.rankingPolicy) && (
              <aside className="ranking-policy" aria-label="추천 순위 기준">
                <strong>추천 순위 기준</strong>
                <p>{result.rankingPolicy}</p>
              </aside>
            )}

            {result && allResultItems.length > 0 ? (
              <>
                {pricedResultItems.length > 0 && (
                  <div className="results-list">
                    {pricedResultItems.map((item, index) => (
                      <div className="ranked-card" key={item.product.id}>
                        <span className="rank-badge">추천 {index + 1}</span>
                        <ProductCard
                          item={item}
                          saved={savedIds.has(item.product.id)}
                          priority={index === 0}
                          compareSelected={compareIds.has(item.product.id)}
                          onToggleProductComparison={toggleProductComparison}
                          onToggleSaved={toggleSaved}
                          onCompareOffers={openOfferComparison}
                          onOpenInformation={openInformationUrl}
                        />
                      </div>
                    ))}
                  </div>
                )}

                {unpricedResultItems.length > 0 && (
                  <section className="additional-candidates" aria-labelledby="additional-candidates-title">
                    <div className="additional-candidates-heading">
                      <span aria-hidden="true">💡</span>
                      <div>
                        <h2 id="additional-candidates-title">가격 정보 없는 추가 후보</h2>
                        <p>피부 조건에는 맞지만 현재 가격을 확인할 수 없어 예산 내 상품으로 확정하지 않았어요.</p>
                      </div>
                    </div>
                    <div className="results-list">
                      {unpricedResultItems.map((item) => (
                        <div className="ranked-card" key={item.product.id}>
                          <span className="rank-badge rank-badge--additional">추가 후보</span>
                          <ProductCard
                            item={item}
                            saved={savedIds.has(item.product.id)}
                            compareSelected={compareIds.has(item.product.id)}
                            onToggleProductComparison={toggleProductComparison}
                            onToggleSaved={toggleSaved}
                            onCompareOffers={openOfferComparison}
                            onOpenInformation={openInformationUrl}
                          />
                        </div>
                      ))}
                    </div>
                  </section>
                )}
              </>
            ) : (
              <div className="empty-state">
                <span aria-hidden="true">🔍</span>
                <h2>조건에 맞는 제품을 찾지 못했어요</h2>
                <p>피해야 할 성분은 유지하고, 예산·제형·제품 종류를 조정해 다시 찾아보세요.</p>
              </div>
            )}

            {allResultItems.length >= 2 && (
              <div className="compare-tray" aria-label="제품 비교 목록">
                <div>
                  <strong>제품 비교</strong>
                  <span>{compareItems.length}/5개 선택</span>
                </div>
                <button
                  type="button"
                  disabled={compareItems.length < 2}
                  onClick={() => navigate('compare')}
                >
                  {compareItems.length < 2 ? '2개 이상 골라주세요' : `${compareItems.length}개 비교하기`}
                </button>
              </div>
            )}

            <div className="guardrail-note">
              <strong>구매 전 확인해 주세요</strong>
              <p>피부 반응은 개인마다 달라요. 민감 피부는 소량으로 패치 테스트하고, 가격·재고는 판매처에서 다시 확인해 주세요.</p>
              <details className="data-source-details">
                <summary>출처와 외부 링크 안내</summary>
                <p>상품·성분·리뷰 출처는 카드마다 실제 제공처 이름으로 구분해 표시해요. 공개 정보는 오래됐거나 누락될 수 있어요.</p>
                <p>판매처 링크는 정보 제공용이며, <strong>광고·제휴</strong> 표시가 있는 링크를 통한 구매에만 수수료가 발생할 수 있어요.</p>
                {allResultItems.some((item) => item.product.catalogSource === 'open_beauty_facts') && (
                  <>
                    <p>Open Beauty Facts 데이터는 ODbL, 상품 이미지는 CC BY-SA 조건으로 제공돼요.</p>
                    <div className="license-links" aria-label="Open Beauty Facts 라이선스">
                      <button type="button" onClick={() => openInformationUrl(OBF_DATA_LICENSE_URL)}>데이터 ODbL 1.0</button>
                      <button type="button" onClick={() => openInformationUrl(OBF_IMAGE_LICENSE_URL)}>이미지 CC BY-SA 3.0</button>
                    </div>
                  </>
                )}
              </details>
            </div>

            <button type="button" className="secondary-button" onClick={goHome}>조건 바꿔 다시 찾기</button>
          </div>
        ) : screen === 'compare' ? (
          <div className="compare-screen">
            <section className="compare-heading">
              <span className="eyebrow">한눈에 비교</span>
              <h1>{compareItems.length}개 제품 비교</h1>
              <p>조건 적합도와 데이터 신뢰도는 서로 다른 정보예요. 가격과 성분 출처도 함께 확인해 보세요.</p>
            </section>

            {compareItems.length >= 2 ? (
              <div className="comparison-table-wrap" tabIndex={0} aria-label="선택 제품 비교표, 좌우로 스크롤할 수 있어요">
                <table className="comparison-table">
                  <thead>
                    <tr>
                      <th scope="col">비교 항목</th>
                      {compareItems.map((item) => (
                        <th scope="col" key={item.product.id}>
                          <span>{item.product.brand}</span>
                          {productDisplayName(item)}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <th scope="row">조건 적합도</th>
                      {compareItems.map((item) => <td key={item.product.id}>{matchLabel(item.score)}</td>)}
                    </tr>
                    <tr>
                      <th scope="row">데이터 신뢰도</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>{item.dataConfidence?.labelKo || '확인 중'}</td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row">핵심 추천 이유</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>{customerReasons(item)[0] || '추천 기준을 충족한 후보'}</td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row">주요 성분</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>
                          {item.matchedIngredients.slice(0, 3).join(', ') || '맞춤 성분 정보 부족'}
                        </td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row">주의 정보</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>{customerCaution(item) || '표시된 주의 정보 없음'}</td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row">확인 가격</th>
                      {compareItems.map((item) => {
                        const summary = offerSummary(item.product);
                        return (
                          <td key={item.product.id}>
                            {summary.lowestPrice !== undefined
                              ? formatPrice(summary.lowestPrice, summary.currency)
                              : '가격 정보 부족'}
                          </td>
                        );
                      })}
                    </tr>
                    <tr>
                      <th scope="row">용량</th>
                      {compareItems.map((item) => <td key={item.product.id}>용량 정보 부족</td>)}
                    </tr>
                    <tr>
                      <th scope="row">10mL당 가격</th>
                      {compareItems.map((item) => <td key={item.product.id}>용량 정보 부족</td>)}
                    </tr>
                    <tr>
                      <th scope="row">상품 출처</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>{productSourceNames(item.product).join(', ') || '출처 정보 확인 중'}</td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row">성분 출처</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>{ingredientSourceNames(item.product).join(', ') || '성분 출처 확인 중'}</td>
                      ))}
                    </tr>
                    <tr>
                      <th scope="row">리뷰 출처</th>
                      {compareItems.map((item) => (
                        <td key={item.product.id}>{reviewSourceNames(item.product).join(', ') || '리뷰 출처 확인 중'}</td>
                      ))}
                    </tr>
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="empty-state">
                <span aria-hidden="true">🧴</span>
                <h2>비교할 제품을 2개 이상 골라주세요</h2>
                <p>추천 결과에서 최대 5개까지 비교 목록에 담을 수 있어요.</p>
              </div>
            )}
            <button type="button" className="secondary-button" onClick={goBack}>추천 결과로 돌아가기</button>
          </div>
        ) : (
          <div className="saved-screen">
            <section className="saved-heading">
              <span className="eyebrow">나의 뷰티 리스트</span>
              <h1>찜한 제품</h1>
              <p>마음에 든 제품을 모아두고 나중에 다시 확인해요.</p>
            </section>

            {savedItems.length > 0 ? (
              <div className="saved-list">
                {savedItems.map((item) => (
                  <ProductCard
                    key={item.product.id}
                    item={item}
                    saved
                    compact
                    onToggleSaved={toggleSaved}
                    onCompareOffers={openOfferComparison}
                    onOpenInformation={openInformationUrl}
                  />
                ))}
              </div>
            ) : (
              <div className="empty-state empty-state--saved">
                <span aria-hidden="true"><HeartIcon /></span>
                <h2>아직 찜한 제품이 없어요</h2>
                <p>추천 결과에서 하트를 누르면 여기에 모아드려요.</p>
                <button type="button" className="primary-button" onClick={goHome}>제품 추천받기</button>
              </div>
            )}
          </div>
        )}
      </main>

      <footer className="data-controls">
        <button type="button" onClick={openPrivacyNotice}>개인정보 처리 안내</button>
        <button type="button" onClick={() => void deleteAllData()}>내 데이터 삭제</button>
      </footer>

      {offerDialog && (
        <OfferComparisonDialog
          item={offerDialog.item}
          offers={offerDialog.offers}
          loading={offerDialog.loading}
          error={offerDialog.error}
          onRetry={() => void refreshOffers(offerDialog.item)}
          onClose={closeOfferDialog}
          onOpenError={showToast}
        />
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

export default App;
