import { graniteEvent } from '@apps-in-toss/web-framework';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react';
import {
  deleteAnonymousSessionData,
  privacyPolicyUrl,
  requestProductOffers,
  requestRecommendations,
} from './api';
import { openExternalUrl } from './external';
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
const CATEGORY_QUESTION_TITLE_ID = 'category-question-title';
const OBF_DATA_LICENSE_URL = 'https://opendatacommons.org/licenses/odbl/1-0/';
const OBF_IMAGE_LICENSE_URL = 'https://creativecommons.org/licenses/by-sa/3.0/';
const OBF_DATA_URL = 'https://world.openbeautyfacts.org/data';

const SKIN_OPTIONS = [
  { value: 'oily', label: '지성' },
  { value: 'dry', label: '건성' },
  { value: 'combination', label: '복합성' },
  { value: 'sensitive', label: '민감성' },
  { value: 'normal', label: '보통' },
] as const;

const CATEGORY_OPTIONS = [
  { value: 'cleanser', label: '클렌저', icon: '🫧' },
  { value: 'toner', label: '토너', icon: '💧' },
  { value: 'serum', label: '세럼', icon: '✨' },
  { value: 'moisturizer', label: '크림', icon: '🧴' },
  { value: 'sunscreen', label: '선크림', icon: '☀️' },
] as const;

const CONCERN_OPTIONS = [
  { value: 'acne', label: '트러블' },
  { value: 'oil_control', label: '유분' },
  { value: 'hydration', label: '수분 부족' },
  { value: 'barrier_support', label: '피부 장벽' },
  { value: 'redness', label: '붉은기' },
  { value: 'hyperpigmentation', label: '잡티' },
  { value: 'clogged_pores', label: '모공' },
  { value: 'dryness', label: '건조함' },
] as const;

const TEXTURE_OPTIONS = [
  { value: 'lightweight', label: '산뜻하게' },
  { value: 'gel', label: '젤 타입' },
  { value: 'dewy', label: '촉촉하게' },
  { value: 'rich', label: '꾸덕하게' },
] as const;

const BUDGET_OPTIONS = [
  { value: null, label: '제한 없음' },
  { value: 20_000, label: '2만원 이하' },
  { value: 30_000, label: '3만원 이하' },
  { value: 50_000, label: '5만원 이하' },
] as const;

const AVOID_OPTIONS = [
  { value: 'fragrance', label: '향료' },
  { value: 'alcohol', label: '에탄올' },
  { value: 'retinol', label: '레티노이드' },
  { value: 'salicylic acid', label: '살리실산' },
] as const;

const INITIAL_ANSWERS: SurveyAnswers = {
  skinType: '',
  category: '',
  concerns: [],
  texture: '',
  budget: null,
  avoidIngredients: [],
  avoidIngredientsText: '',
  privacyConsent: false,
};

type Screen = 'survey' | 'results' | 'saved';

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
    isOptionalString(product.ingredientStatus) &&
    isOptionalString(product.recommendationTier) &&
    isOptionalString(product.dataLicense) &&
    isOptionalString(product.dataAttributionUrl) &&
    isSavedExternalLinks(product.externalLinks) &&
    isOptionalNumber(product.priceKrw) &&
    isOptionalNumber(product.rating) &&
    isOptionalNumber(product.reviewCount) &&
    isOptionalString(product.reviewSummary) &&
    isStringArray(product.ingredients) &&
    (product.offers === undefined || Array.isArray(product.offers)) &&
    typeof value.reason === 'string' &&
    isOptionalNumber(value.score) &&
    isStringArray(value.cautions) &&
    isStringArray(value.matchedIngredients)
  );
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
    return value.filter((item): item is RecommendationItem => {
      if (!isSavedRecommendationItem(item) || seenIds.has(item.product.id)) {
        return false;
      }
      item.product.offers ??= [];
      seenIds.add(item.product.id);
      return true;
    });
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
        value.product.offers ??= [];
        cache[id] = withoutDynamicOfferData(value);
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
      offers: [],
    },
    reason: '추천을 다시 실행하면 최신 제품 정보를 확인할 수 있어요.',
    cautions: [],
    matchedIngredients: [],
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

function sourceLabel(item: RecommendationItem): string {
  if (item.product.catalogSource === 'open_beauty_facts') {
    return '공개 상품 정보';
  }
  return '상품 정보';
}

function sourceDate(item: RecommendationItem): string {
  const value = item.product.sourceUpdatedAt;
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
  compact?: boolean;
  priority?: boolean;
}

function ProductCard({
  item,
  saved,
  onToggleSaved,
  onCompareOffers,
  onOpenInformation,
  compact = false,
  priority = false,
}: ProductCardProps) {
  const { product } = item;
  const summary = offerSummary(product);
  const [imageFailed, setImageFailed] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const imageUrl = imageFailed ? undefined : product.imageUrl;
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

        {(product.rating || product.reviewCount) && (
          <p className="rating-row">
            <span aria-hidden="true">★</span>
            {product.rating?.toFixed(1) || '리뷰'}
            {product.reviewCount ? ` · 리뷰 ${new Intl.NumberFormat('ko-KR').format(product.reviewCount)}개` : ''}
          </p>
        )}

        <div className="source-row">
          <span>{sourceLabel(item)}</span>
          {sourceDate(item) && <span>정보 기준 {sourceDate(item)}</span>}
          {informationLinks.map((link) => (
            <button
              type="button"
              key={`${link.kind}:${link.url}`}
              onClick={() => onOpenInformation(link.url)}
            >
              {link.label}
            </button>
          ))}
        </div>

        {!compact && (
          <>
            <section className="reason-box" aria-label="추천 이유">
              <span className="reason-icon">
                <SparkleIcon />
              </span>
              <div>
                <strong>이 제품을 고른 이유</strong>
                <p>{item.reason}</p>
              </div>
            </section>

            {item.matchedIngredients.length > 0 && (
              <div className="ingredient-row" aria-label="주요 성분">
                {item.matchedIngredients.slice(0, 4).map((ingredient) => (
                  <span key={ingredient}>{ingredient}</span>
                ))}
              </div>
            )}

            {item.cautions.length > 0 && (
              <p className="caution-row">
                <strong>확인해 주세요</strong> {item.cautions.slice(0, 2).join(' ')}
              </p>
            )}
          </>
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
        onClose();
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
  }, [onClose]);

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
  const categoryQuestionRef = useRef<HTMLElement | null>(null);
  const privacyConsentRef = useRef<HTMLInputElement | null>(null);

  const savedIds = useMemo(() => new Set(savedProductIds), [savedProductIds]);
  const currentItems = useMemo(
    () => new Map((result?.items || []).map((item) => [item.product.id, item])),
    [result],
  );
  const savedItems = useMemo(
    () => savedProductIds
      .map((id) => currentItems.get(id) || savedItemCache[id] || savedItemPlaceholder(id)),
    [currentItems, savedItemCache, savedProductIds],
  );

  useEffect(() => {
    try {
      const cache = Object.fromEntries(
        savedProductIds
          .map((id) => [id, savedItemCache[id]] as const)
          .filter((entry): entry is readonly [string, RecommendationItem] => Boolean(entry[1])),
      );
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

  async function deleteAllData() {
    try {
      await deleteAnonymousSessionData();
      for (const key of [
        LEGACY_SAVED_STORAGE_KEY,
        SAVED_IDS_STORAGE_KEY,
        SAVED_CACHE_STORAGE_KEY,
        SAVED_ISSUED_AT_KEY,
      ]) {
        window.localStorage.removeItem(key);
      }
      setSavedProductIds([]);
      setSavedItemCache({});
      setResult(null);
      setAnswers(INITIAL_ANSWERS);
      setError('');
      setValidation('');
      goHome();
      showToast('서버와 기기에 저장된 내 데이터를 삭제했어요.');
    } catch (deleteError) {
      showToast(deleteError instanceof Error ? deleteError.message : '데이터를 삭제하지 못했어요.');
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

  async function runRecommendation() {
    if (!answers.skinType || !answers.category) {
      const missingSkinType = !answers.skinType;
      const missingCategory = !answers.category;
      setValidation(
        missingSkinType && missingCategory
          ? '피부 타입과 찾는 제품을 먼저 선택해 주세요.'
          : `${missingSkinType ? '피부 타입' : '찾는 제품'}을 먼저 선택해 주세요.`,
      );

      const question = missingSkinType ? skinQuestionRef.current : categoryQuestionRef.current;
      const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
      question?.scrollIntoView({ behavior: prefersReducedMotion ? 'auto' : 'smooth', block: 'center' });
      window.requestAnimationFrame(() => {
        question?.querySelector<HTMLButtonElement>('button')?.focus({ preventScroll: true });
      });
      return;
    }

    if (!answers.privacyConsent) {
      setValidation('맞춤 추천을 저장하려면 개인정보 처리 안내를 확인하고 동의해 주세요.');
      privacyConsentRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      window.requestAnimationFrame(() => privacyConsentRef.current?.focus({ preventScroll: true }));
      return;
    }

    setValidation('');
    setError('');
    setLoading(true);
    try {
      const nextResult = await requestRecommendations(answers);
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
                    <p>가장 가까운 하나를 골라주세요.</p>
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

              <section className="question-section" ref={categoryQuestionRef}>
                <div className="question-title">
                  <span>2</span>
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

              <section className="question-section">
                <div className="question-title">
                  <span>3</span>
                  <div>
                    <h2>요즘 가장 신경 쓰이는 고민은요?</h2>
                    <p>여러 개 골라도 괜찮아요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={CONCERN_OPTIONS}
                  selected={answers.concerns}
                  multiple
                  onSelect={(value) =>
                    setAnswers((current) => ({ ...current, concerns: toggleInList(current.concerns, value) }))
                  }
                />
              </section>

              <section className="question-section">
                <div className="question-title">
                  <span>4</span>
                  <div>
                    <h2>좋아하는 사용감이 있나요?</h2>
                    <p>건너뛰어도 추천받을 수 있어요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={TEXTURE_OPTIONS}
                  selected={answers.texture}
                  onSelect={(value) => setAnswers((current) => ({ ...current, texture: current.texture === value ? '' : value }))}
                />
              </section>

              <section className="question-section">
                <div className="question-title">
                  <span>5</span>
                  <div>
                    <h2>예산은 어느 정도인가요?</h2>
                    <p>가격 정보가 없는 제품은 판매처에서 직접 확인할 수 있어요.</p>
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

              <section className="question-section question-section--last">
                <div className="question-title">
                  <span>6</span>
                  <div>
                    <h2>피하고 싶은 성분이 있나요?</h2>
                    <p>목록에 없으면 피하고 싶은 성분명을 직접 입력할 수 있어요.</p>
                  </div>
                </div>
                <ChipGroup
                  options={AVOID_OPTIONS}
                  selected={answers.avoidIngredients}
                  multiple
                  onSelect={(value) =>
                    setAnswers((current) => ({
                      ...current,
                      avoidIngredients: toggleInList(current.avoidIngredients, value),
                    }))
                  }
                />
                <label className="text-field">
                  <span>직접 입력</span>
                  <input
                    type="text"
                    value={answers.avoidIngredientsText}
                    maxLength={120}
                    placeholder="예: 티트리 오일, 라놀린"
                    onChange={(event) =>
                      setAnswers((current) => ({ ...current, avoidIngredientsText: event.target.value }))
                    }
                  />
                  <small>알레르기·임신·수유 같은 건강정보는 입력하지 말고, 피할 성분명만 적어 주세요.</small>
                </label>
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
                  <span>피부 정보와 피해야 할 성분으로 만든 통제 프로필을 맞춤 추천에 사용하고 최대 30일 보관하는 데 동의합니다.</span>
                </label>
                <button type="button" onClick={openPrivacyNotice}>개인정보 처리 안내</button>
              </div>

              <button type="submit" className="primary-button">
                내 피부 맞춤 제품 찾기
                <ArrowIcon />
              </button>
              <p className="privacy-note">로그인 없이 사용할 수 있고, 언제든 아래에서 내 데이터를 삭제할 수 있어요.</p>
            </form>
          </div>
        ) : screen === 'results' ? (
          <div className="results-screen">
            <section className="results-heading">
              <span className="eyebrow">맞춤 분석 완료</span>
              <h1>{result?.items.length || 0}개 제품을 골랐어요</h1>
              <p>{result?.summary}</p>
            </section>

            {result?.rankingPolicy && (
              <aside className="ranking-policy" aria-label="추천 순위 기준">
                <strong>추천 순위 기준</strong>
                <p>{result.rankingPolicy}</p>
              </aside>
            )}

            {result && result.items.length > 0 ? (
              <div className="results-list">
                {result.items.map((item, index) => (
                  <div className="ranked-card" key={item.product.id}>
                    <span className="rank-badge">추천 {index + 1}</span>
                    <ProductCard
                      item={item}
                      saved={savedIds.has(item.product.id)}
                      priority={index === 0}
                      onToggleSaved={toggleSaved}
                      onCompareOffers={openOfferComparison}
                      onOpenInformation={openInformationUrl}
                    />
                  </div>
                ))}
              </div>
            ) : (
              <div className="empty-state">
                <span aria-hidden="true">🔍</span>
                <h2>조건에 맞는 제품을 찾지 못했어요</h2>
                <p>피해야 할 성분은 유지하고, 예산·제형·제품 종류를 조정해 다시 찾아보세요.</p>
              </div>
            )}

            <div className="guardrail-note">
              <strong>구매 전 확인해 주세요</strong>
              <p>피부 반응은 개인마다 달라요. 민감 피부는 소량으로 패치 테스트하고, 가격·재고는 판매처에서 다시 확인해 주세요.</p>
              <details className="data-source-details">
                <summary>데이터 출처 안내</summary>
                <p>일부 공개 상품 정보는 오래됐거나 누락될 수 있어요. Open Beauty Facts 데이터는 ODbL, 상품 이미지는 CC BY-SA 조건으로 제공돼요.</p>
                <div className="license-links" aria-label="Open Beauty Facts 라이선스">
                  <button type="button" onClick={() => openInformationUrl(OBF_DATA_LICENSE_URL)}>데이터 ODbL 1.0</button>
                  <button type="button" onClick={() => openInformationUrl(OBF_IMAGE_LICENSE_URL)}>이미지 CC BY-SA 3.0</button>
                </div>
              </details>
            </div>

            <button type="button" className="secondary-button" onClick={goHome}>조건 바꿔 다시 찾기</button>
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
