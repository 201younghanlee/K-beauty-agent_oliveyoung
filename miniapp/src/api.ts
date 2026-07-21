import { Storage } from '@apps-in-toss/web-framework';
import type {
  ApiErrorBody,
  CommerceSummary,
  Product,
  ProductExternalLink,
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
const SESSION_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
export const PRIVACY_POLICY_VERSION = '2026-07-20';

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '');

let memorySessionToken = '';
let memorySessionIssuedAt = 0;

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

export async function getAnonymousSessionToken(): Promise<string> {
  if (SESSION_PATTERN.test(memorySessionToken) && validIssuedAt(memorySessionIssuedAt)) {
    return memorySessionToken;
  }

  try {
    const [stored, storedIssuedAt] = await Promise.all([
      Storage.getItem(SESSION_STORAGE_KEY),
      Storage.getItem(SESSION_ISSUED_AT_KEY),
    ]);
    const issuedAt = Number(storedIssuedAt || 0);
    if (typeof stored === 'string' && SESSION_PATTERN.test(stored) && validIssuedAt(issuedAt)) {
      memorySessionToken = stored;
      memorySessionIssuedAt = issuedAt;
      saveBrowserSession(stored, issuedAt);
      return stored;
    }
  } catch {
    // 일반 브라우저 또는 SDK 브리지 오류에서는 Web Storage로 이어갑니다.
  }

  const browserSession = readBrowserSession();
  const useBrowserSession = SESSION_PATTERN.test(browserSession.token) && validIssuedAt(browserSession.issuedAt);
  const token = useBrowserSession ? browserSession.token : createSessionToken();
  const issuedAt = useBrowserSession ? browserSession.issuedAt : Date.now();
  memorySessionToken = token;
  memorySessionIssuedAt = issuedAt;
  saveBrowserSession(token, issuedAt);

  try {
    await Promise.all([
      Storage.setItem(SESSION_STORAGE_KEY, token),
      Storage.setItem(SESSION_ISSUED_AT_KEY, String(issuedAt)),
    ]);
  } catch {
    // 네이티브 저장소를 쓸 수 없는 로컬 브라우저에서도 토큰은 유지됩니다.
  }
  return token;
}

export function privacyPolicyUrl(): string {
  return `${API_BASE_URL}/privacy`;
}

export async function deleteAnonymousSessionData(): Promise<void> {
  const token = await getAnonymousSessionToken();
  const response = await fetch(`${API_BASE_URL}/api/session`, {
    method: 'DELETE',
    mode: 'cors',
    credentials: 'omit',
    cache: 'no-store',
    headers: { 'X-KBeauty-Session': token },
  });
  if (!response.ok) {
    throw new Error(await readErrorMessage(response));
  }
  memorySessionToken = '';
  memorySessionIssuedAt = 0;
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
    // The server-side deletion already completed; stale local keys expire on the next rotation.
  }
}

function buildQuery(answers: SurveyAnswers): string {
  const skinLabels: Record<string, string> = {
    oily: '지성',
    dry: '건성',
    combination: '복합성',
    sensitive: '민감성',
    normal: '보통',
  };
  const categoryLabels: Record<string, string> = {
    cleanser: '클렌저',
    toner: '토너',
    serum: '세럼',
    moisturizer: '수분크림',
    sunscreen: '선크림',
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
  };
  const textureLabels: Record<string, string> = {
    lightweight: '산뜻한',
    gel: '젤',
    dewy: '촉촉한',
    rich: '꾸덕한',
  };

  const parts = [
    `피부 타입은 ${skinLabels[answers.skinType] ?? answers.skinType}(${answers.skinType})이고`,
    `${categoryLabels[answers.category] ?? answers.category}(${answers.category}) 제품을 추천해줘.`,
  ];

  if (answers.concerns.length > 0) {
    const concerns = answers.concerns.map((item) => `${concernLabels[item] ?? item}(${item})`).join(', ');
    parts.push(`피부 고민은 ${concerns}이야.`);
  }
  if (answers.texture) {
    parts.push(`제형은 ${textureLabels[answers.texture] ?? answers.texture}(${answers.texture}) 타입을 선호해.`);
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

  return parts.join(' ');
}

export function buildStructuredProfile(answers: SurveyAnswers) {
  const freeformAvoid = answers.avoidIngredientsText
    .split(/[,，]/)
    .map((item) => item.trim().slice(0, 50))
    .filter(Boolean);
  const avoidIngredients = [...new Set([...answers.avoidIngredients, ...freeformAvoid])].slice(0, 12);

  return {
    skin_type: answers.skinType,
    concerns: answers.concerns,
    desired_categories: answers.category ? [answers.category] : [],
    avoid_ingredients: avoidIngredients,
    ...(answers.budget ? { max_price_krw: answers.budget } : {}),
    ...(answers.texture ? { texture_preference: answers.texture } : {}),
  };
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

function normalizeProduct(rawItem: Record<string, unknown>): Product | null {
  const nested = isRecord(rawItem.product) ? rawItem.product : rawItem;
  const id = firstText(nested.id, nested.product_id);
  const name = firstText(nested.name, nested.product_name);
  if (!id || !name) {
    return null;
  }

  const review = isRecord(nested.review) ? nested.review : {};
  const offers = normalizeV2Offers(rawItem, nested);
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
    rating: asNumber(nested.rating),
    reviewCount: asNumber(nested.review_count),
    reviewSummary:
      firstText(nested.review_summary, nested.positive_review, review.summary, review.positive) || undefined,
    ingredients: asStringArray(nested.ingredients),
    catalogSource: firstText(nested.catalog_source) || undefined,
    sourceUpdatedAt: firstText(nested.source_updated_at, nested.verified_at) || undefined,
    ingredientStatus: firstText(nested.ingredient_status) || undefined,
    recommendationTier: firstText(nested.recommendation_tier) || undefined,
    dataLicense: firstText(nested.data_license) || undefined,
    dataAttributionUrl: firstText(nested.data_attribution_url) || undefined,
    externalLinks: normalizeExternalLinks(nested.external_links),
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

  return {
    product,
    score: asNumber(value.score),
    reason: reason || '선택한 피부 조건과 제품 정보의 적합도를 기준으로 추천했어요.',
    cautions: cautionSource.filter((caution) => !isOperationalPriceDiagnostic(caution)),
    matchedIngredients: asStringArray(value.display_matched_ingredients).length
      ? asStringArray(value.display_matched_ingredients)
      : asStringArray(value.matched_ingredients).length
        ? asStringArray(value.matched_ingredients)
        : product.ingredients.slice(0, 3),
  };
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
  const items = rawItems.map(normalizeItem).filter((item): item is RecommendationItem => item !== null);
  const sourceStatus = isRecord(payload.product_source_status) ? payload.product_source_status : {};
  const catalogTotal = asNumber(sourceStatus.total_products);

  return {
    decision: firstText(payload.decision) || (items.length > 0 ? 'recommend' : 'fallback'),
    summary: items.length > 0
      ? '선택한 조건을 바탕으로 제품 성분과 피부 적합도를 비교했어요.'
      : '피해야 할 성분을 유지한 상태에서 다른 선택 조건을 조정해 다시 찾아보세요.',
    items,
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
    const sessionToken = await getAnonymousSessionToken();
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
    const sessionToken = await getAnonymousSessionToken();
    const response = await fetch(`${API_BASE_URL}/api/v2/products/${encodeURIComponent(productId)}/offers`, {
      method: 'GET',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: { 'X-KBeauty-Session': sessionToken },
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
