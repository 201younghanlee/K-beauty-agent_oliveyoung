import { Storage } from '@apps-in-toss/web-framework';
import type {
  ApiErrorBody,
  CommerceSummary,
  DataConfidence,
  IngredientExplanation,
  Product,
  ProductExternalLink,
  ProductVideoReview,
  ProductVideoReviews,
  RecommendationItem,
  RecommendationResult,
  RetailOffer,
  SurveyAnswers,
} from './types';

const DEFAULT_API_BASE_URL = 'https://k-beauty-recommendation-agent-gafd.onrender.com';
const SESSION_STORAGE_KEY = 'kBeautyAgentAnonymousSessionV1';
const SESSION_ISSUED_AT_KEY = 'kBeautyAgentAnonymousSessionIssuedAtV1';
const SESSION_PATTERN = /^[A-Za-z0-9_-]{20,128}$/;
const REQUEST_TIMEOUT_MS = 60_000;
const VIDEO_REVIEW_TIMEOUT_MS = 25_000;
const DELETE_TIMEOUT_MS = 12_000;
const SESSION_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
export const PRIVACY_POLICY_VERSION = '2026-07-22';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '');

let memoryPersistentSessionToken = '';
let memoryPersistentSessionIssuedAt = 0;

function createSessionToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  const body = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `kb_${body}`;
}

function validIssuedAt(value: unknown): value is number {
  const issuedAt = typeof value === 'number' ? value : Number(value);
  const age = Date.now() - issuedAt;
  return Number.isFinite(issuedAt) && age >= 0 && age < SESSION_MAX_AGE_MS;
}

function readBrowserSession(): { token: string; issuedAt: number } {
  try {
    return {
      token: window.localStorage.getItem(SESSION_STORAGE_KEY) || '',
      issuedAt: Number(window.localStorage.getItem(SESSION_ISSUED_AT_KEY) || 0),
    };
  } catch {
    return { token: '', issuedAt: 0 };
  }
}

function saveBrowserSession(value: string, issuedAt: number): void {
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, value);
    window.localStorage.setItem(SESSION_ISSUED_AT_KEY, String(issuedAt));
  } catch {
    // Web Storage가 막힌 환경에서는 메모리와 네이티브 Storage를 사용합니다.
  }
}

async function readPersistentSessionToken(): Promise<string | undefined> {
  if (
    SESSION_PATTERN.test(memoryPersistentSessionToken)
    && validIssuedAt(memoryPersistentSessionIssuedAt)
  ) {
    return memoryPersistentSessionToken;
  }
  memoryPersistentSessionToken = '';
  memoryPersistentSessionIssuedAt = 0;

  try {
    const [stored, storedIssuedAt] = await Promise.all([
      Storage.getItem(SESSION_STORAGE_KEY),
      Storage.getItem(SESSION_ISSUED_AT_KEY),
    ]);
    const issuedAt = Number(storedIssuedAt || 0);
    if (typeof stored === 'string' && SESSION_PATTERN.test(stored) && validIssuedAt(issuedAt)) {
      memoryPersistentSessionToken = stored;
      memoryPersistentSessionIssuedAt = issuedAt;
      return stored;
    }
  } catch {
    // 일반 브라우저 또는 SDK 브리지 오류에서는 Web Storage로 이어갑니다.
  }

  const browserSession = readBrowserSession();
  if (SESSION_PATTERN.test(browserSession.token) && validIssuedAt(browserSession.issuedAt)) {
    memoryPersistentSessionToken = browserSession.token;
    memoryPersistentSessionIssuedAt = browserSession.issuedAt;
    return browserSession.token;
  }
  return undefined;
}

async function savePersistentSessionToken(token: string, issuedAt: number): Promise<void> {
  memoryPersistentSessionToken = token;
  memoryPersistentSessionIssuedAt = issuedAt;
  saveBrowserSession(token, issuedAt);

  try {
    await Promise.all([
      Storage.setItem(SESSION_STORAGE_KEY, token),
      Storage.setItem(SESSION_ISSUED_AT_KEY, String(issuedAt)),
    ]);
  } catch {
    // 네이티브 저장소를 쓸 수 없는 로컬 브라우저에서도 토큰은 유지됩니다.
  }
}

async function clearPersistentSessionToken(): Promise<void> {
  memoryPersistentSessionToken = '';
  memoryPersistentSessionIssuedAt = 0;
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    window.localStorage.removeItem(SESSION_ISSUED_AT_KEY);
  } catch {
    // Native storage cleanup below remains authoritative inside Apps in Toss.
  }
  try {
    await Promise.all([
      Storage.removeItem(SESSION_STORAGE_KEY),
      Storage.removeItem(SESSION_ISSUED_AT_KEY),
    ]);
  } catch {
    // Invalid or expired native keys will be ignored by readPersistentSessionToken.
  }
}

export async function getAnonymousSessionToken(persist = true): Promise<string> {
  if (!persist) {
    // One-time recommendations use a request-scoped identifier only. It is not
    // copied into memory, localStorage, sessionStorage, or Apps in Toss Storage.
    return createSessionToken();
  }

  const existingToken = await readPersistentSessionToken();
  if (existingToken) {
    return existingToken;
  }

  const token = createSessionToken();
  await savePersistentSessionToken(token, Date.now());
  return token;
}

export function privacyPolicyUrl(): string {
  return `${API_BASE_URL}/privacy`;
}

export function termsOfUseUrl(): string {
  return `${API_BASE_URL}/terms`;
}

export async function deleteAnonymousSessionData(): Promise<void> {
  const token = await readPersistentSessionToken();
  if (!token) {
    await clearPersistentSessionToken();
    return;
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), DELETE_TIMEOUT_MS);
  try {
    const response = await fetch(`${API_BASE_URL}/api/session`, {
      method: 'DELETE',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: { 'X-KBeauty-Session': token },
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    await clearPersistentSessionToken();
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('서버 삭제 요청 시간이 초과됐어요. 네트워크가 안정되면 다시 시도해 주세요.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

function buildQuery(answers: SurveyAnswers): string {
  const skinLabels: Record<string, string> = {
    oily: '지성',
    dry: '건성',
    combination: '복합성',
    normal: '중성',
    unknown: '잘 모르겠음',
  };
  const categoryLabels: Record<string, string> = {
    cleanser: '클렌저',
    toner: '토너',
    serum: '세럼·앰플·에센스',
    moisturizer: '수분크림',
    sunscreen: '선크림',
    face_mask: '마스크팩',
    eye_care: '아이케어',
    lip_care: '립케어',
    exfoliator: '각질케어',
    body_cleanser: '바디워시',
    body_moisturizer: '바디 보습',
    body_exfoliator: '바디 각질 케어',
    shampoo: '샴푸',
    conditioner: '컨디셔너',
    hair_treatment: '헤어 트리트먼트',
    base_makeup: '베이스 메이크업',
    eye_makeup: '아이 메이크업',
    lip_makeup: '립 메이크업',
    basic: '필요한 제품 단계 추천',
  };
  const concernLabels: Record<string, string> = {
    acne: '트러블',
    oil_control: '유분 조절',
    hydration: '수분 부족',
    barrier_support: '피부 장벽',
    redness: '붉은기',
    hyperpigmentation: '잡티',
    clogged_pores: '막힌 모공',
    dryness: '건조함',
    dullness: '칙칙함·톤 불균일',
    texture: '피부결·거칠음',
    anti_aging: '탄력·잔주름',
  };
  const textureLabels: Record<string, string> = {
    watery: '워터리',
    gel: '젤',
    lotion: '로션',
    cream: '크림',
    rich: '밤·리치',
  };
  const sensitivityLabels: Record<string, string> = {
    frequent: '쉽게 따갑거나 붉어짐',
    occasional: '가끔 예민해짐',
    low: '거의 민감하지 않음',
  };
  const finishLabels: Record<string, string> = {
    fresh: '산뜻함',
    low_sticky: '끈적임 적음',
    moist: '촉촉함',
    glow: '쫀쫀·윤기',
    matte: '보송함',
  };

  const parts = [
    `피부 타입은 ${skinLabels[answers.skinType] ?? answers.skinType}(${answers.skinType})이고`,
    `${categoryLabels[answers.category] ?? answers.category}(${answers.category}) 제품을 추천해줘.`,
  ];

  if (answers.sensitivity) {
    parts.push(`민감도는 ${sensitivityLabels[answers.sensitivity] ?? answers.sensitivity}(${answers.sensitivity})이야.`);
  }

  if (answers.primaryConcern) {
    parts.push(`1순위 피부 고민은 ${concernLabels[answers.primaryConcern] ?? answers.primaryConcern}(${answers.primaryConcern})이야.`);
  }
  if (answers.concerns.length > 0) {
    const concerns = answers.concerns.map((item) => `${concernLabels[item] ?? item}(${item})`).join(', ');
    parts.push(`추가 피부 고민은 ${concerns}이야.`);
  }
  if (answers.texture) {
    parts.push(`제형은 ${textureLabels[answers.texture] ?? answers.texture}(${answers.texture}) 타입을 선호해.`);
  }
  if (answers.finish) {
    parts.push(`마무리감은 ${finishLabels[answers.finish] ?? answers.finish}(${answers.finish})을 선호해.`);
  }
  if (answers.budget) {
    parts.push(`최대 예산은 ${answers.budget}원이야.`);
  }

  const freeformAvoid = answers.avoidIngredientsText
    .split(/[,，]/)
    .map((item) => item.trim())
    .filter(Boolean);
  const avoid = [...new Set([...answers.avoidIngredients, ...freeformAvoid])];
  if (avoid.length > 0) {
    parts.push(`피해야 할 성분은 ${avoid.join(', ')}이야.`);
  }

  const freeformPreferred = splitIngredientText(answers.preferredIngredientsText);
  const preferred = [...new Set([...answers.preferredIngredients, ...freeformPreferred])];
  if (preferred.length > 0) {
    parts.push(`선호 성분은 ${preferred.join(', ')}이야. 없어도 제외하지 말고 순위에만 반영해줘.`);
  }

  return parts.join(' ');
}

export function buildStructuredProfile(answers: SurveyAnswers) {
  const freeformAvoid = answers.avoidIngredientsText
    .split(/[,，]/)
    .map((item) => item.trim().slice(0, 50))
    .filter(Boolean);
  const avoidIngredients = [...new Set([...answers.avoidIngredients, ...freeformAvoid])].slice(0, 12);
  const preferredIngredients = [...new Set([
    ...answers.preferredIngredients,
    ...splitIngredientText(answers.preferredIngredientsText),
  ])].slice(0, 12);
  const concerns = [...new Set([
    ...(answers.primaryConcern ? [answers.primaryConcern] : []),
    ...answers.concerns.filter((item) => item !== answers.primaryConcern),
  ])].slice(0, 3);

  return {
    skin_type: answers.skinType,
    ...(answers.sensitivity ? { sensitivity_level: answers.sensitivity } : {}),
    ...(answers.primaryConcern ? { primary_concern: answers.primaryConcern } : {}),
    concerns,
    desired_categories: answers.category ? [answers.category] : [],
    avoid_ingredients: avoidIngredients,
    preferred_ingredients: preferredIngredients,
    ...(answers.budget ? { max_price_krw: answers.budget } : {}),
    ...(answers.texture ? { texture_preference: answers.texture } : {}),
    ...(answers.finish ? { finish_preference: answers.finish } : {}),
  };
}

function splitIngredientText(value: string): string[] {
  return value
    .split(/[,，]/)
    .map((item) => item.trim().slice(0, 50))
    .filter(Boolean);
}

const INGREDIENT_ALIASES: Record<string, string> = {
  '향료': 'fragrance',
  'parfum': 'fragrance',
  '에탄올': 'ethanol',
  'ethyl alcohol': 'ethanol',
  'alcohol denat.': 'ethanol',
  'alcohol denat': 'ethanol',
  'denatured alcohol': 'ethanol',
  '알코올': 'alcohol',
  '레티놀': 'retinol',
  '레티노이드': 'retinol',
  '살리실산': 'salicylic acid',
  'bha': 'salicylic acid',
  '나이아신아마이드': 'niacinamide',
  'nicotinamide': 'niacinamide',
  'vitamin b3': 'niacinamide',
  '비타민 b3': 'niacinamide',
  '히알루론산': 'hyaluronic acid',
  '세라마이드': 'ceramide',
  '판테놀': 'panthenol',
  '병풀': 'centella asiatica',
  '시카': 'centella asiatica',
};

function ingredientKey(value: string): string {
  const normalized = value.trim().toLowerCase().replace(/[-_]+/g, ' ').replace(/\s+/g, ' ');
  return INGREDIENT_ALIASES[normalized] ?? normalized;
}

export function ingredientSelectionConflicts(answers: SurveyAnswers): string[] {
  const avoided = new Map(
    [...answers.avoidIngredients, ...splitIngredientText(answers.avoidIngredientsText)]
      .map((item) => [ingredientKey(item), item] as const),
  );
  const preferred = new Map(
    [...answers.preferredIngredients, ...splitIngredientText(answers.preferredIngredientsText)]
      .map((item) => [ingredientKey(item), item] as const),
  );
  return [...preferred.keys()].filter((key) => avoided.has(key)).map((key) => preferred.get(key) || key);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function asString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function asNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : undefined;
  }
  return undefined;
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.map(asString).filter(Boolean);
}

function firstText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) {
      return value.trim();
    }
    const list = asStringArray(value);
    if (list.length > 0) {
      return list.join(' · ');
    }
  }
  return '';
}

function asAbsoluteAssetUrl(value: unknown): string | undefined {
  const url = asString(value);
  if (!url) {
    return undefined;
  }
  try {
    return new URL(url, `${API_BASE_URL}/`).toString();
  } catch {
    return undefined;
  }
}

function asBackendRedirectUrl(value: unknown): string | undefined {
  const url = asString(value);
  if (!url) {
    return undefined;
  }
  try {
    const apiOrigin = new URL(`${API_BASE_URL}/`).origin;
    const parsed = new URL(url, `${API_BASE_URL}/`);
    return parsed.protocol === 'https:' && parsed.origin === apiOrigin && parsed.pathname.startsWith('/r/')
      ? parsed.toString()
      : undefined;
  } catch {
    return undefined;
  }
}

function asBoolean(value: unknown): boolean | undefined {
  if (typeof value === 'boolean') {
    return value;
  }
  if (typeof value === 'number') {
    return value !== 0;
  }
  if (typeof value === 'string') {
    const normalized = value.trim().toLowerCase();
    if (['true', '1', 'yes'].includes(normalized)) {
      return true;
    }
    if (['false', '0', 'no'].includes(normalized)) {
      return false;
    }
  }
  return undefined;
}

function normalizeAvailability(...values: unknown[]): RetailOffer['availability'] {
  const value = firstText(...values).toLowerCase().replace(/[\s-]+/g, '_');
  if (['in_stock', 'available', 'on_sale', '판매중', '재고있음'].includes(value)) {
    return 'in_stock';
  }
  if (['preorder', 'pre_order', '예약판매'].includes(value)) {
    return 'preorder';
  }
  if (['out_of_stock', 'sold_out', 'unavailable', '품절', '재고없음'].includes(value)) {
    return 'out_of_stock';
  }
  return 'unknown';
}

function normalizeOffer(value: unknown, index: number): RetailOffer | null {
  if (!isRecord(value)) {
    return null;
  }

  const retailer = isRecord(value.retailer) ? value.retailer : {};
  const price = isRecord(value.price) ? value.price : {};
  const listPrice = isRecord(value.list_price)
    ? value.list_price
    : isRecord(value.listPrice)
      ? value.listPrice
      : {};
  const freshness = isRecord(value.freshness) ? value.freshness : {};
  const stock = isRecord(value.stock) ? value.stock : {};
  const affiliateDetails = isRecord(value.affiliate) ? value.affiliate : {};
  const retailerName = firstText(
    value.retailer_name,
    value.retailerName,
    value.merchant_name,
    value.store_name,
    retailer.name,
  );
  if (!retailerName) {
    return null;
  }

  const id = firstText(value.id, value.offer_id, value.offerId)
    || `${firstText(value.retailer_id, value.retailerId, retailer.id) || retailerName}-${index}`;
  const fresh = asBoolean(value.is_fresh ?? value.isFresh ?? value.fresh ?? freshness.is_fresh);
  const stale = asBoolean(value.is_stale ?? value.isStale ?? value.stale ?? freshness.is_stale);
  const freshnessStatus = firstText(value.freshness_status, freshness.status).toLowerCase();
  const affiliate = asBoolean(
    value.is_affiliate
    ?? value.isAffiliate
    ?? (isRecord(value.affiliate)
      ? affiliateDetails.active ?? affiliateDetails.enabled ?? affiliateDetails.is_affiliate
      : value.affiliate),
  );
  const relationship = firstText(value.relationship, value.link_type, value.linkType).toLowerCase();
  const currency = (firstText(value.currency, price.currency) || 'KRW').toUpperCase();
  const priceAmount = asNumber(
    value.price_krw
    ?? value.priceKrw
    ?? value.sale_price_krw
    ?? value.salePriceKrw
    ?? value.current_price
    ?? price.amount_krw
    ?? price.amount,
  );
  const listPriceAmount = asNumber(
    value.list_price_krw
    ?? value.listPriceKrw
    ?? value.original_price_krw
    ?? value.originalPriceKrw
    ?? listPrice.amount_krw
    ?? listPrice.amount
    ?? value.list_price
    ?? price.list_amount_krw
    ?? price.list_amount,
  );

  return {
    id,
    retailerId: firstText(value.retailer_id, value.retailerId, retailer.id) || undefined,
    retailerName,
    priceAmount,
    listPriceAmount,
    priceKrw: currency === 'KRW' ? priceAmount : undefined,
    listPriceKrw: currency === 'KRW' ? listPriceAmount : undefined,
    currency,
    availability: normalizeAvailability(
      value.availability,
      value.availability_status,
      value.availabilityStatus,
      value.stock_status,
      value.stockStatus,
      stock.status,
    ),
    isStale: stale ?? (fresh === false || ['stale', 'expired'].includes(freshnessStatus)),
    checkedAt: firstText(
      value.checked_at,
      value.checkedAt,
      value.price_checked_at,
      value.priceCheckedAt,
      value.observed_at,
      value.updated_at,
      freshness.checked_at,
    ) || undefined,
    // 외부 목적지를 프런트에서 만들지 않고 API가 내려준 클릭 URL만 사용합니다.
    clickUrl: asBackendRedirectUrl(
      value.click_url
      ?? value.clickUrl
      ?? value.redirect_url
      ?? value.redirectUrl,
    ),
    isLinkOnly: asBoolean(value.link_only ?? value.linkOnly) ?? false,
    linkType: firstText(value.link_type, value.linkType) === 'retailer_search'
      ? 'retailer_search'
      : 'product_page',
    isAffiliate: affiliate ?? relationship === 'affiliate',
    affiliateLabel: firstText(
      value.affiliate_label,
      value.affiliateLabel,
      affiliateDetails.label,
    ) || undefined,
    affiliateDisclosure: firstText(
      value.affiliate_disclosure,
      value.affiliateDisclosure,
      value.disclosure,
      affiliateDetails.disclosure,
      affiliateDetails.disclosure_ko,
    ) || undefined,
  };
}

function normalizeCommerce(value: unknown): CommerceSummary | undefined {
  if (!isRecord(value)) {
    return undefined;
  }

  const retailerCount = asNumber(value.retailer_count ?? value.retailerCount) ?? 0;
  const offerCount = asNumber(value.offer_count ?? value.offerCount) ?? retailerCount;
  const freshOfferCount = asNumber(value.fresh_offer_count ?? value.freshOfferCount) ?? 0;
  const bestCurrentPrice = isRecord(value.best_current_price) ? value.best_current_price : {};
  const bestCurrentPriceCurrency = firstText(bestCurrentPrice.currency).toUpperCase();
  const lowestFreshPriceKrw = asNumber(
    value.lowest_fresh_price_krw
    ?? value.lowestFreshPriceKrw
    ?? value.lowest_price_krw
    ?? value.lowestPriceKrw
    ?? (bestCurrentPriceCurrency === 'KRW' ? bestCurrentPrice.amount : undefined),
  );
  const hasAffiliateOffers = asBoolean(
    value.has_affiliate_offers ?? value.hasAffiliateOffers ?? value.has_affiliate,
  ) ?? false;
  const lowestFreshPriceCurrency = firstText(
    value.lowest_fresh_price_currency,
    value.lowestFreshPriceCurrency,
    bestCurrentPriceCurrency,
  ) || undefined;

  if (retailerCount === 0 && offerCount === 0 && freshOfferCount === 0 && lowestFreshPriceKrw === undefined) {
    return undefined;
  }
  return {
    retailerCount,
    offerCount,
    freshOfferCount,
    lowestFreshPriceKrw,
    lowestFreshPriceCurrency,
    hasAffiliateOffers,
  };
}

function normalizeV2Offers(rawItem: Record<string, unknown>, nested: Record<string, unknown>): RetailOffer[] {
  const rawOffers = Array.isArray(rawItem.offers)
    ? rawItem.offers
    : Array.isArray(nested.offers)
      ? nested.offers
      : Array.isArray(rawItem.retail_offers)
        ? rawItem.retail_offers
        : Array.isArray(nested.retail_offers)
          ? nested.retail_offers
          : [];

  const seenIds = new Set<string>();
  return rawOffers
    .map(normalizeOffer)
    .filter((offer): offer is RetailOffer => {
      if (!offer || seenIds.has(offer.id)) {
        return false;
      }
      seenIds.add(offer.id);
      return true;
    });
}

function normalizeExternalLinks(value: unknown): ProductExternalLink[] {
  if (!Array.isArray(value)) {
    return [];
  }
  const allowedKinds = new Set<ProductExternalLink['kind']>([
    'brand_official',
    'ingredient_reference',
    'data_reference',
    'review_reference',
  ]);
  const seen = new Set<string>();
  const links: ProductExternalLink[] = [];
  for (const rawLink of value) {
    if (!isRecord(rawLink)) {
      continue;
    }
    const kind = firstText(rawLink.kind) as ProductExternalLink['kind'];
    const label = firstText(rawLink.label);
    const provider = firstText(rawLink.provider);
    const rawUrl = firstText(rawLink.url);
    if (!allowedKinds.has(kind) || !label || !provider || !rawUrl) {
      continue;
    }
    try {
      const parsed = new URL(rawUrl);
      if (parsed.protocol !== 'https:' || parsed.username || parsed.password || seen.has(parsed.toString())) {
        continue;
      }
      seen.add(parsed.toString());
      links.push({ kind, label, provider, url: parsed.toString() });
    } catch {
      // Ignore malformed or untrusted source metadata.
    }
  }
  return links;
}

function reviewUrlFromVerifiedLinks(
  value: unknown,
  links: ProductExternalLink[],
): string | undefined {
  const rawUrl = firstText(value);
  if (!rawUrl) {
    return undefined;
  }
  try {
    const normalized = new URL(rawUrl).toString();
    return links.find((link) => link.url === normalized)?.url;
  } catch {
    return undefined;
  }
}

function normalizeIngredientExplanations(value: unknown): IngredientExplanation[] {
  if (!Array.isArray(value)) {
    return [];
  }
  return value.flatMap((raw): IngredientExplanation[] => {
    if (!isRecord(raw)) {
      return [];
    }
    const name = firstText(raw.name);
    const label = firstText(raw.label, raw.display_name_ko, raw.name);
    if (!name || !label) {
      return [];
    }
    return [{
      name,
      label,
      displayNameKo: firstText(raw.display_name_ko) || undefined,
      supports: asStringArray(raw.supports),
      displaySupportsKo: asStringArray(raw.display_supports_ko),
      cautions: asStringArray(raw.cautions),
      displayCautionsKo: asStringArray(raw.display_cautions_ko),
      evidenceLevel: firstText(raw.evidence_level) || undefined,
      rationale: firstText(raw.rationale) || undefined,
      displayRationaleKo: firstText(raw.display_rationale_ko) || undefined,
    }];
  }).slice(0, 30);
}

function normalizeConfidenceFactor(value: unknown) {
  if (!isRecord(value)) {
    return undefined;
  }
  const status = firstText(value.status);
  const labelKo = firstText(value.label_ko, value.labelKo);
  if (!status || !labelKo) {
    return undefined;
  }
  return {
    status,
    labelKo,
    checkedAt: firstText(value.checked_at, value.checkedAt) || undefined,
    dateKind: firstText(value.date_kind, value.dateKind) || undefined,
    sourceUrl: firstText(value.source_url, value.sourceUrl) || undefined,
  };
}

function normalizeDataConfidence(value: unknown): DataConfidence | undefined {
  if (!isRecord(value)) {
    return undefined;
  }
  const level = firstText(value.level);
  const labelKo = firstText(value.label_ko, value.labelKo);
  if (!['high', 'medium', 'low'].includes(level) || !labelKo) {
    return undefined;
  }
  const factors = isRecord(value.factors) ? value.factors : {};
  return {
    level: level as DataConfidence['level'],
    labelKo,
    factors: {
      ingredients: normalizeConfidenceFactor(factors.ingredients),
      productSource: normalizeConfidenceFactor(factors.product_source ?? factors.productSource),
      reviews: normalizeConfidenceFactor(factors.reviews),
    },
  };
}

function normalizeProduct(rawItem: Record<string, unknown>): Product | null {
  const nested = isRecord(rawItem.product) ? rawItem.product : rawItem;
  const id = firstText(nested.id, nested.product_id);
  const name = firstText(nested.name, nested.product_name);
  if (!id || !name) {
    return null;
  }

  const review = isRecord(nested.review) ? nested.review : {};
  const offers = normalizeV2Offers(rawItem, nested);
  const externalLinks = normalizeExternalLinks(nested.external_links);
  const reviewSourceUrl = reviewUrlFromVerifiedLinks(
    firstText(nested.review_source_url, review.source_url, review.sourceUrl),
    externalLinks,
  );
  return {
    id,
    name,
    displayNameKo: firstText(nested.display_name_ko, nested.name_ko) || undefined,
    brand: firstText(nested.brand) || '브랜드 정보 없음',
    category: firstText(nested.category) || 'skincare',
    imageUrl: asAbsoluteAssetUrl(firstText(nested.image_url, nested.thumbnail_url)),
    oliveyoungUrl: firstText(nested.oliveyoung_url) || undefined,
    purchaseUrl: firstText(nested.purchase_url, nested.oliveyoung_url) || undefined,
    sourceUrl: firstText(nested.source_url) || undefined,
    officialUrl: firstText(nested.official_url) || undefined,
    retailerName: firstText(nested.retailer_name) || undefined,
    priceKrw: asNumber(nested.price_krw ?? nested.oliveyoung_price_krw),
    priceCheckedAt: firstText(nested.price_checked_at, nested.oliveyoung_verified_at) || undefined,
    rating: reviewSourceUrl ? asNumber(nested.rating) : undefined,
    reviewCount: reviewSourceUrl ? asNumber(nested.review_count) : undefined,
    reviewSummary: reviewSourceUrl
      ? firstText(nested.review_summary, nested.positive_review, review.summary, review.positive) || undefined
      : undefined,
    reviewSourceUrl,
    reviewVerifiedAt: reviewSourceUrl ? firstText(
      nested.review_verified_at,
      nested.review_checked_at,
      review.verified_at,
      review.checked_at,
      review.verifiedAt,
      review.checkedAt,
    ) || undefined : undefined,
    ingredients: asStringArray(nested.ingredients),
    claims: asStringArray(nested.claims),
    concerns: asStringArray(nested.concerns),
    textureTags: asStringArray(nested.texture_tags),
    ingredientExplanations: normalizeIngredientExplanations(nested.ingredient_explanations),
    catalogSource: firstText(nested.catalog_source) || undefined,
    sourceUpdatedAt: firstText(nested.source_updated_at, nested.verified_at) || undefined,
    ingredientStatus: firstText(nested.ingredient_status) || undefined,
    recommendationTier: firstText(nested.recommendation_tier) || undefined,
    dataLicense: firstText(nested.data_license) || undefined,
    dataAttributionUrl: firstText(nested.data_attribution_url) || undefined,
    externalLinks,
    commerce: normalizeCommerce(nested.commerce),
    // V1 purchase URLs are informational legacy fields only. The miniapp opens
    // offers exclusively through the signed same-origin `/r/` route from V2.
    offers,
  };
}

function isOperationalPriceDiagnostic(value: string): boolean {
  const normalized = value.trim().toLowerCase();
  return [
    'price is missing, so cannot verify',
    'checked price is missing, so cannot verify',
    'olive young price is missing, so cannot verify',
    'checked 가격 데이터가 없어',
    '가격 데이터가 없어 최대 가격 조건을 확인할 수 없음',
    '최근 확인된 가격이 없어 최대 가격 조건을 확인할 수 없음',
    '최근 확인된 가격이 없어 최소 가격 조건을 확인할 수 없음',
    '올리브영 가격 데이터가 없어 최대 가격 조건을 확인할 수 없음',
    'excluded because checked price',
    'excluded because listed price',
    '가격이 요청한 최대 가격을 초과해 제외',
    '가격이 요청한 최소 가격보다 낮아 제외',
  ].some((fragment) => normalized.includes(fragment));
}

function customerReason(value: string): string {
  for (const separator of [' 다만 ', ' Note: ']) {
    const boundary = value.lastIndexOf(separator);
    if (boundary > 0 && isOperationalPriceDiagnostic(value.slice(boundary + separator.length))) {
      return value.slice(0, boundary).trim();
    }
  }
  return isOperationalPriceDiagnostic(value) ? '' : value;
}

function normalizeItem(value: unknown): RecommendationItem | null {
  if (!isRecord(value)) {
    return null;
  }
  const product = normalizeProduct(value);
  if (!product) {
    return null;
  }

  const reason = customerReason(firstText(
    value.personalized_reason,
    value.display_reasons,
    value.ai_recommendation_explanation,
    value.reasons,
    value.why_recommended,
    value.why,
  ));
  const cautionSource = Array.isArray(value.display_cautions)
    ? asStringArray(value.display_cautions)
    : asStringArray(value.cautions);

  const displayReasons = asStringArray(value.display_reasons)
    .map(customerReason)
    .filter(Boolean);

  return {
    product,
    score: asNumber(value.score),
    reason: reason || '선택한 피부 조건과 제품 정보의 적합도를 기준으로 추천했어요.',
    reasons: displayReasons.length > 0
      ? displayReasons
      : [reason || '선택한 피부 조건과 제품 정보의 적합도를 기준으로 추천했어요.'],
    cautions: cautionSource.filter((caution) => !isOperationalPriceDiagnostic(caution)),
    matchedIngredients: asStringArray(value.display_matched_ingredients).length
      ? asStringArray(value.display_matched_ingredients)
      : asStringArray(value.matched_ingredients).length
        ? asStringArray(value.matched_ingredients)
        : product.ingredients.slice(0, 3),
    missingData: asStringArray(value.missing_data).length
      ? asStringArray(value.missing_data)
      : asStringArray(value.display_missing_data),
    dataConfidence: normalizeDataConfidence(value.data_confidence),
  };
}

function responseHasPriceConstraint(payload: Record<string, unknown>): boolean {
  const profile = isRecord(payload.profile) ? payload.profile : {};
  return [
    profile.max_price_krw,
    profile.maxPriceKrw,
    profile.min_price_krw,
    profile.minPriceKrw,
    profile.max_price_usd,
    profile.maxPriceUsd,
    profile.min_price_usd,
    profile.minPriceUsd,
  ].some((value) => asNumber(value) !== undefined);
}

function hasMissingPrice(item: RecommendationItem): boolean {
  return item.missingData.some((value) => {
    const normalized = value.trim().toLowerCase();
    return normalized === 'price' || normalized === '가격';
  });
}

function dedupeItems(items: RecommendationItem[]): RecommendationItem[] {
  const seen = new Set<string>();
  return items.filter((item) => {
    if (seen.has(item.product.id)) {
      return false;
    }
    seen.add(item.product.id);
    return true;
  });
}

export function normalizeResponse(payload: unknown): RecommendationResult {
  if (!isRecord(payload)) {
    throw new Error('서버 응답 형식을 확인할 수 없어요.');
  }

  const rawItems = Array.isArray(payload.results)
    ? payload.results
    : Array.isArray(payload.recommendations)
      ? payload.recommendations
      : [];
  let items = dedupeItems(
    rawItems.map(normalizeItem).filter((item): item is RecommendationItem => item !== null),
  );
  const hasExplicitAdditionalCandidates = Array.isArray(payload.additional_candidates);
  let additionalCandidates = hasExplicitAdditionalCandidates
    ? dedupeItems(
      (payload.additional_candidates as unknown[])
        .map(normalizeItem)
        .filter((item): item is RecommendationItem => item !== null),
    )
    : [];

  if (hasExplicitAdditionalCandidates) {
    const additionalIds = new Set(additionalCandidates.map((item) => item.product.id));
    items = items.filter((item) => !additionalIds.has(item.product.id));
  } else if (responseHasPriceConstraint(payload)) {
    additionalCandidates = items.filter(hasMissingPrice);
    items = items.filter((item) => !hasMissingPrice(item));
  }
  const sourceStatus = isRecord(payload.product_source_status) ? payload.product_source_status : {};
  const catalogTotal = asNumber(sourceStatus.total_products);

  return {
    decision: firstText(payload.decision)
      || (items.length > 0 || additionalCandidates.length > 0 ? 'recommend' : 'fallback'),
    summary: items.length > 0
      ? '선택한 조건을 바탕으로 제품 성분과 피부 적합도를 비교했어요.'
      : additionalCandidates.length > 0
        ? '현재 가격이 확인된 제품은 없지만, 조건에 맞는 추가 후보를 찾았어요.'
        : '피해야 할 성분을 유지한 상태에서 다른 선택 조건을 조정해 다시 찾아보세요.',
    items,
    additionalCandidates,
    catalogTotal,
    rankingPolicy: firstText(payload.ranking_policy, payload.rankingPolicy) || undefined,
  };
}

export function normalizeOffersResponse(payload: unknown): RetailOffer[] {
  const container = isRecord(payload) && isRecord(payload.data) ? payload.data : payload;
  const rawOffers = Array.isArray(container)
    ? container
    : isRecord(container) && Array.isArray(container.offers)
      ? container.offers
      : [];

  const seenIds = new Set<string>();
  return rawOffers
    .map(normalizeOffer)
    .filter((offer): offer is RetailOffer => {
      if (!offer || seenIds.has(offer.id)) {
        return false;
      }
      seenIds.add(offer.id);
      return true;
    });
}

const YOUTUBE_VIDEO_ID_PATTERN = /^[A-Za-z0-9_-]{11}$/;
const YOUTUBE_CHANNEL_ID_PATTERN = /^UC[A-Za-z0-9_-]{22}$/;
const YOUTUBE_HOSTS = new Set(['www.youtube.com']);
const YOUTUBE_THUMBNAIL_HOSTS = new Set(['i.ytimg.com', 'img.youtube.com']);
const YOUTUBE_CHANNEL_THUMBNAIL_HOSTS = new Set(['yt3.ggpht.com', 'yt3.googleusercontent.com']);

function asExactHttpsUrl(
  value: unknown,
  allowedHosts: ReadonlySet<string>,
  allowedPaths?: ReadonlySet<string>,
): string | undefined {
  const rawUrl = firstText(value);
  if (!rawUrl) {
    return undefined;
  }
  try {
    const parsed = new URL(rawUrl);
    if (
      parsed.protocol !== 'https:'
      || parsed.username
      || parsed.password
      || parsed.port
      || !allowedHosts.has(parsed.hostname)
      || (allowedPaths && !allowedPaths.has(parsed.pathname))
    ) {
      return undefined;
    }
    return parsed.toString();
  } catch {
    return undefined;
  }
}

function asNonNegativeInteger(...values: unknown[]): number | undefined {
  for (const value of values) {
    if (
      typeof value === 'number'
      && Number.isSafeInteger(value)
      && value >= 0
    ) {
      return value;
    }
    if (typeof value === 'string' && /^(0|[1-9]\d*)$/.test(value.trim())) {
      const parsed = Number(value);
      if (Number.isSafeInteger(parsed)) {
        return parsed;
      }
    }
  }
  return undefined;
}

function asYouTubeChannelUrl(value: unknown, channelId: string): string | undefined {
  const url = asExactHttpsUrl(value, YOUTUBE_HOSTS);
  if (!url || !YOUTUBE_CHANNEL_ID_PATTERN.test(channelId)) {
    return undefined;
  }
  const parsed = new URL(url);
  if (
    parsed.pathname !== `/channel/${channelId}`
    || parsed.search
    || parsed.hash
  ) {
    return undefined;
  }
  return parsed.toString();
}

function normalizeYouTubeVideo(value: unknown): ProductVideoReview | null {
  if (!isRecord(value)) {
    return null;
  }
  const videoId = firstText(value.video_id, value.videoId);
  const title = firstText(value.title);
  const channelTitle = firstText(value.channel_title, value.channelTitle);
  const url = asExactHttpsUrl(value.url, YOUTUBE_HOSTS, new Set(['/watch']));
  if (!YOUTUBE_VIDEO_ID_PATTERN.test(videoId) || !title || !channelTitle || !url) {
    return null;
  }
  if (new URL(url).searchParams.get('v') !== videoId) {
    return null;
  }
  const channelId = firstText(value.channel_id, value.channelId);
  const safeChannelId = YOUTUBE_CHANNEL_ID_PATTERN.test(channelId) ? channelId : undefined;
  return {
    videoId,
    title: title.slice(0, 240),
    channelTitle: channelTitle.slice(0, 160),
    publishedAt: firstText(value.published_at, value.publishedAt).slice(0, 40) || undefined,
    duration: firstText(value.duration).slice(0, 32) || undefined,
    thumbnailUrl: asExactHttpsUrl(
      value.thumbnail_url ?? value.thumbnailUrl,
      YOUTUBE_THUMBNAIL_HOSTS,
    ),
    viewCount: asNonNegativeInteger(value.view_count, value.viewCount),
    likeCount: asNonNegativeInteger(value.like_count, value.likeCount),
    channelId: safeChannelId,
    channelThumbnailUrl: asExactHttpsUrl(
      value.channel_thumbnail_url ?? value.channelThumbnailUrl,
      YOUTUBE_CHANNEL_THUMBNAIL_HOSTS,
    ),
    subscriberCount: asNonNegativeInteger(value.subscriber_count, value.subscriberCount),
    subscriberCountHidden: asBoolean(
      value.subscriber_count_hidden ?? value.subscriberCountHidden,
    ) ?? false,
    channelUrl: safeChannelId
      ? asYouTubeChannelUrl(value.channel_url ?? value.channelUrl, safeChannelId)
      : undefined,
    url,
    hasPaidProductPlacement: asBoolean(
      value.has_paid_product_placement ?? value.hasPaidProductPlacement,
    ) ?? false,
  };
}

export function normalizeProductVideoReviews(payload: unknown): ProductVideoReviews {
  if (!isRecord(payload)) {
    throw new Error('YouTube 후기 응답 형식을 확인할 수 없어요.');
  }
  const status = firstText(payload.status);
  const allowedStatuses = new Set<ProductVideoReviews['status']>([
    'ready',
    'search_only',
    'no_results',
    'temporarily_unavailable',
    'quota_limited',
  ]);
  const searchUrl = asExactHttpsUrl(
    payload.search_url ?? payload.searchUrl,
    YOUTUBE_HOSTS,
    new Set(['/results']),
  );
  const termsUrl = asExactHttpsUrl(
    payload.terms_url ?? payload.termsUrl,
    YOUTUBE_HOSTS,
    new Set(['/t/terms']),
  );
  const privacyUrl = asExactHttpsUrl(
    payload.privacy_url ?? payload.privacyUrl,
    new Set(['policies.google.com']),
    new Set(['/privacy']),
  );
  if (
    payload.provider !== 'YouTube'
    || !allowedStatuses.has(status as ProductVideoReviews['status'])
    || !searchUrl
    || !termsUrl
    || !privacyUrl
  ) {
    throw new Error('YouTube 후기 응답의 출처를 확인할 수 없어요.');
  }

  const seen = new Set<string>();
  const videos = (Array.isArray(payload.videos) ? payload.videos : [])
    .map(normalizeYouTubeVideo)
    .filter((video): video is ProductVideoReview => {
      if (!video || seen.has(video.videoId)) {
        return false;
      }
      seen.add(video.videoId);
      return true;
    })
    .slice(0, 3);

  return {
    provider: 'YouTube',
    status: status as ProductVideoReviews['status'],
    query: firstText(payload.query).slice(0, 240),
    searchUrl,
    messageKo: firstText(payload.message_ko, payload.messageKo).slice(0, 300),
    disclaimerKo: firstText(payload.disclaimer_ko, payload.disclaimerKo).slice(0, 500),
    termsUrl,
    privacyUrl,
    videos,
  };
}

async function readErrorMessage(response: Response): Promise<string> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    if (typeof body.detail === 'string') {
      return body.detail;
    }
    if (Array.isArray(body.detail)) {
      const messages = body.detail.map((item) => item.msg).filter(Boolean);
      if (messages.length > 0) {
        return messages.join(', ');
      }
    }
    if (body.message) {
      return body.message;
    }
  } catch {
    // JSON이 아닌 오류 응답은 상태 코드 기반 문구를 사용합니다.
  }
  return `추천 서버가 응답하지 않았어요. (${response.status})`;
}

export async function requestRecommendations(answers: SurveyAnswers): Promise<RecommendationResult> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const conflicts = ingredientSelectionConflicts(answers);
    if (conflicts.length > 0) {
      throw new Error(`선호 성분과 제외 성분이 겹쳐요: ${conflicts.join(', ')}. 한쪽 선택을 해제해 주세요.`);
    }
    const sessionToken = await getAnonymousSessionToken(answers.privacyConsent);
    const body = JSON.stringify({
      query: buildQuery(answers),
      limit: 5,
      use_openai: false,
      language: 'ko',
      profile: buildStructuredProfile(answers),
      privacy_consent: answers.privacyConsent,
      privacy_policy_version: PRIVACY_POLICY_VERSION,
    });
    const requestOptions: RequestInit = {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        'X-KBeauty-Session': sessionToken,
      },
      body,
      signal: controller.signal,
    };
    let response = await fetch(`${API_BASE_URL}/api/v2/recommend`, requestOptions);
    if ([404, 405, 501].includes(response.status)) {
      response = await fetch(`${API_BASE_URL}/api/recommend`, requestOptions);
    }

    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    return normalizeResponse(await response.json());
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('추천 준비가 오래 걸리고 있어요. 잠시 후 다시 시도해 주세요.');
    }
    if (error instanceof TypeError) {
      throw new Error('네트워크 연결을 확인한 뒤 다시 시도해 주세요.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function requestProductOffers(productId: string): Promise<RetailOffer[]> {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const sessionToken = await readPersistentSessionToken();
    const headers = sessionToken ? { 'X-KBeauty-Session': sessionToken } : undefined;
    const response = await fetch(`${API_BASE_URL}/api/v2/products/${encodeURIComponent(productId)}/offers`, {
      method: 'GET',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers,
      signal: controller.signal,
    });
    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    return normalizeOffersResponse(await response.json());
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('판매처 정보를 불러오는 데 시간이 걸리고 있어요. 다시 시도해 주세요.');
    }
    if (error instanceof TypeError) {
      throw new Error('네트워크 연결을 확인한 뒤 다시 시도해 주세요.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}

export async function requestProductVideoReviews(
  productId: string,
  policyAccepted: boolean,
): Promise<ProductVideoReviews> {
  if (!policyAccepted) {
    throw new Error('YouTube 관련 영상 기능의 이용조건과 개인정보 처리 안내에 먼저 동의해 주세요.');
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), VIDEO_REVIEW_TIMEOUT_MS);

  try {
    const response = await fetch(
      `${API_BASE_URL}/api/v2/products/${encodeURIComponent(productId)}/video-reviews?limit=3`,
      {
        method: 'GET',
        mode: 'cors',
        credentials: 'omit',
        cache: 'no-store',
        headers: {
          'X-YouTube-Policy-Accepted': PRIVACY_POLICY_VERSION,
        },
        signal: controller.signal,
      },
    );
    if (!response.ok) {
      throw new Error(await readErrorMessage(response));
    }
    return normalizeProductVideoReviews(await response.json());
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') {
      throw new Error('YouTube 관련 영상을 불러오는 데 시간이 걸리고 있어요. 다시 시도해 주세요.');
    }
    if (error instanceof TypeError) {
      throw new Error('네트워크 연결을 확인한 뒤 다시 시도해 주세요.');
    }
    throw error;
  } finally {
    window.clearTimeout(timeout);
  }
}
