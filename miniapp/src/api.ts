import { Storage } from '@apps-in-toss/web-framework';
import type {
  ApiErrorBody,
  Product,
  RecommendationItem,
  RecommendationResult,
  SurveyAnswers,
} from './types';

const DEFAULT_API_BASE_URL = 'https://k-beauty-recommendation-agent-gafd.onrender.com';
const SESSION_STORAGE_KEY = 'kBeautyAgentAnonymousSessionV1';
const SESSION_PATTERN = /^[A-Za-z0-9_-]{20,128}$/;
const REQUEST_TIMEOUT_MS = 60_000;

const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(/\/$/, '');

let memorySessionToken = '';

function createSessionToken(): string {
  const bytes = new Uint8Array(24);
  crypto.getRandomValues(bytes);
  const body = Array.from(bytes, (value) => value.toString(16).padStart(2, '0')).join('');
  return `kb_${body}`;
}

function readBrowserSessionToken(): string {
  try {
    return window.localStorage.getItem(SESSION_STORAGE_KEY) || '';
  } catch {
    return '';
  }
}

function saveBrowserSessionToken(value: string): void {
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, value);
  } catch {
    // Web Storage가 막힌 환경에서는 메모리와 네이티브 Storage를 사용합니다.
  }
}

export async function getAnonymousSessionToken(): Promise<string> {
  if (SESSION_PATTERN.test(memorySessionToken)) {
    return memorySessionToken;
  }

  try {
    const stored = await Storage.getItem(SESSION_STORAGE_KEY);
    if (typeof stored === 'string' && SESSION_PATTERN.test(stored)) {
      memorySessionToken = stored;
      saveBrowserSessionToken(stored);
      return stored;
    }
  } catch {
    // 일반 브라우저 또는 SDK 브리지 오류에서는 Web Storage로 이어갑니다.
  }

  const browserToken = readBrowserSessionToken();
  const token = SESSION_PATTERN.test(browserToken) ? browserToken : createSessionToken();
  memorySessionToken = token;
  saveBrowserSessionToken(token);

  try {
    await Storage.setItem(SESSION_STORAGE_KEY, token);
  } catch {
    // 네이티브 저장소를 쓸 수 없는 로컬 브라우저에서도 토큰은 유지됩니다.
  }
  return token;
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

function normalizeProduct(rawItem: Record<string, unknown>): Product | null {
  const nested = isRecord(rawItem.product) ? rawItem.product : rawItem;
  const id = firstText(nested.id, nested.product_id);
  const name = firstText(nested.name, nested.product_name);
  if (!id || !name) {
    return null;
  }

  const review = isRecord(nested.review) ? nested.review : {};
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
  };
}

function normalizeItem(value: unknown): RecommendationItem | null {
  if (!isRecord(value)) {
    return null;
  }
  const product = normalizeProduct(value);
  if (!product) {
    return null;
  }

  const reason = firstText(
    value.personalized_reason,
    value.display_reasons,
    value.ai_recommendation_explanation,
    value.reasons,
    value.why_recommended,
    value.why,
  );

  return {
    product,
    score: asNumber(value.score),
    reason: reason || '선택한 피부 조건과 제품 정보의 적합도를 기준으로 추천했어요.',
    cautions: asStringArray(value.display_cautions).length
      ? asStringArray(value.display_cautions)
      : asStringArray(value.cautions),
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
    const sessionToken = await getAnonymousSessionToken();
    const response = await fetch(`${API_BASE_URL}/api/recommend`, {
      method: 'POST',
      mode: 'cors',
      credentials: 'omit',
      cache: 'no-store',
      headers: {
        'Content-Type': 'application/json',
        'X-KBeauty-Session': sessionToken,
      },
      body: JSON.stringify({
        query: buildQuery(answers),
        limit: 5,
        use_openai: false,
        language: 'ko',
        profile: buildStructuredProfile(answers),
      }),
      signal: controller.signal,
    });

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
