import { graniteEvent } from '@apps-in-toss/web-framework';
import { useEffect, useMemo, useRef, useState, type CSSProperties, type FormEvent } from 'react';
import { requestRecommendations } from './api';
import { oliveYoungSearchUrl, openExternalUrl } from './external';
import type { RecommendationItem, RecommendationResult, SurveyAnswers } from './types';
import { useSafeAreaInsets } from './useSafeArea';

const SAVED_STORAGE_KEY = 'kBeautyAgentSavedProductsV1';
const VALIDATION_MESSAGE_ID = 'survey-validation-message';
const SKIN_QUESTION_TITLE_ID = 'skin-question-title';
const CATEGORY_QUESTION_TITLE_ID = 'category-question-title';

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
    isOptionalNumber(product.priceKrw) &&
    isOptionalNumber(product.rating) &&
    isOptionalNumber(product.reviewCount) &&
    isOptionalString(product.reviewSummary) &&
    isStringArray(product.ingredients) &&
    typeof value.reason === 'string' &&
    isOptionalNumber(value.score) &&
    isStringArray(value.cautions) &&
    isStringArray(value.matchedIngredients)
  );
}

function readSavedItems(): RecommendationItem[] {
  try {
    const value: unknown = JSON.parse(window.localStorage.getItem(SAVED_STORAGE_KEY) || '[]');
    if (!Array.isArray(value)) {
      return [];
    }

    const seenIds = new Set<string>();
    return value.filter((item): item is RecommendationItem => {
      if (!isSavedRecommendationItem(item) || seenIds.has(item.product.id)) {
        return false;
      }
      seenIds.add(item.product.id);
      return true;
    });
  } catch {
    return [];
  }
}

function formatPrice(price?: number): string {
  return price ? `${new Intl.NumberFormat('ko-KR').format(price)}원` : '판매가 미제공';
}

function productDisplayName(item: RecommendationItem): string {
  return item.product.displayNameKo || item.product.name;
}

function sourceLabel(item: RecommendationItem): string {
  if (item.product.catalogSource === 'open_beauty_facts') {
    return 'Open Beauty Facts';
  }
  return item.product.retailerName || '검증 카탈로그';
}

function sourceDate(item: RecommendationItem): string {
  const value = item.product.sourceUpdatedAt || item.product.priceCheckedAt;
  const date = value?.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  return date ? date.replace(/-/g, '.') : '';
}

function productAction(item: RecommendationItem): { label: string; url: string } {
  const { product } = item;
  const purchaseUrl = product.purchaseUrl || product.oliveyoungUrl;
  if (purchaseUrl) {
    return {
      label: product.retailerName ? `${product.retailerName}에서 확인` : '판매처에서 확인',
      url: purchaseUrl,
    };
  }
  if (product.catalogSource === 'open_beauty_facts' && product.sourceUrl) {
    return { label: '제품 데이터·출처 보기', url: product.sourceUrl };
  }
  if (product.officialUrl) {
    return { label: '공식 제품 정보 보기', url: product.officialUrl };
  }
  if (product.sourceUrl) {
    return { label: '제품 정보 보기', url: product.sourceUrl };
  }
  return { label: '올리브영에서 검색', url: oliveYoungSearchUrl(productDisplayName(item)) };
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
  onOpenError: (message: string) => void;
  compact?: boolean;
  priority?: boolean;
}

function ProductCard({
  item,
  saved,
  onToggleSaved,
  onOpenError,
  compact = false,
  priority = false,
}: ProductCardProps) {
  const { product } = item;
  const action = productAction(item);
  const [imageFailed, setImageFailed] = useState(false);
  const [imageLoaded, setImageLoaded] = useState(false);
  const imageUrl = imageFailed ? undefined : product.imageUrl;

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
          <strong className="product-price">{formatPrice(product.priceKrw)}</strong>
        </div>

        {(product.rating || product.reviewCount) && (
          <p className="rating-row">
            <span aria-hidden="true">★</span>
            {product.rating?.toFixed(1) || '리뷰'}
            {product.reviewCount ? ` · 리뷰 ${new Intl.NumberFormat('ko-KR').format(product.reviewCount)}개` : ''}
          </p>
        )}

        <p className="source-row">
          <span>{sourceLabel(item)}</span>
          {sourceDate(item) && <span>데이터 수정 {sourceDate(item)}</span>}
        </p>

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
          onClick={() => {
            void openExternalUrl(action.url).catch((openError: unknown) => {
              onOpenError(openError instanceof Error ? openError.message : '제품 정보 페이지를 열지 못했어요.');
            });
          }}
        >
          {action.label}
          <ArrowIcon />
        </button>
      </div>
    </article>
  );
}

function LoadingPanel() {
  return (
    <div className="loading-panel" role="status" aria-live="polite">
      <div className="loading-orbit" aria-hidden="true">
        <span />
      </div>
      <h2>딱 맞는 제품을 찾고 있어요</h2>
      <p>검증 상품과 글로벌 오픈 카탈로그의 성분을 비교 중이에요.</p>
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
  const [screen, setScreen] = useState<Screen>('survey');
  const [answers, setAnswers] = useState<SurveyAnswers>(INITIAL_ANSWERS);
  const [result, setResult] = useState<RecommendationResult | null>(null);
  const [savedItems, setSavedItems] = useState<RecommendationItem[]>(readSavedItems);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [validation, setValidation] = useState('');
  const [toast, setToast] = useState('');
  const toastTimer = useRef<number | undefined>(undefined);
  const screenStack = useRef<Screen[]>(['survey']);
  const skinQuestionRef = useRef<HTMLElement | null>(null);
  const categoryQuestionRef = useRef<HTMLElement | null>(null);

  const savedIds = useMemo(() => new Set(savedItems.map((item) => item.product.id)), [savedItems]);

  useEffect(() => {
    try {
      window.localStorage.setItem(SAVED_STORAGE_KEY, JSON.stringify(savedItems));
    } catch {
      // 저장 공간이 제한된 환경에서도 현재 세션의 찜 기능은 유지합니다.
    }
  }, [savedItems]);

  useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  useEffect(() => {
    if (screenStack.current.length <= 1) {
      return undefined;
    }

    try {
      return graniteEvent.addEventListener('backEvent', {
        onEvent: () => {
          goBack();
        },
        onError: () => undefined,
      });
    } catch {
      return undefined;
    }
  }, [screen]);

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
    setSavedItems((current) =>
      alreadySaved
        ? current.filter((saved) => saved.product.id !== item.product.id)
        : [item, ...current.filter((saved) => saved.product.id !== item.product.id)],
    );
    showToast(alreadySaved ? '찜 목록에서 삭제했어요.' : '찜 목록에 저장했어요.');
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
                    <p>최근 확인된 판매가가 있는 제품만 예산 조건에 포함돼요.</p>
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
                    <p>알레르기가 있다면 직접 입력해 주세요.</p>
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

              <button type="submit" className="primary-button">
                내 피부 맞춤 제품 찾기
                <ArrowIcon />
              </button>
              <p className="privacy-note">로그인 없이 사용할 수 있고, 선택 내용은 추천에만 사용해요.</p>
            </form>
          </div>
        ) : screen === 'results' ? (
          <div className="results-screen">
            <section className="results-heading">
              <span className="eyebrow">맞춤 분석 완료</span>
              {result?.catalogTotal && (
                <p className="catalog-count">
                  현재 {new Intl.NumberFormat('ko-KR').format(result.catalogTotal)}개 제품 데이터가 있어요 · 선택 조건에 맞는 모든 후보를 비교했어요
                </p>
              )}
              <h1>{result?.items.length || 0}개 제품을 골랐어요</h1>
              <p>{result?.summary}</p>
            </section>

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
                      onOpenError={showToast}
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
              <p>Open Beauty Facts 데이터는 ODbL, 상품 이미지는 CC BY-SA 조건으로 제공돼요. 최신 덤프를 매일 확인하지만 개별 커뮤니티 상품 정보는 오래됐거나 누락될 수 있어요.</p>
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
                    onOpenError={showToast}
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

      {toast && <div className="toast" role="status">{toast}</div>}
    </div>
  );
}

export default App;
