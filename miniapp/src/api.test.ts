import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  buildStructuredProfile,
  ingredientSelectionConflicts,
  normalizeOffersResponse,
  normalizeResponse,
} from './api';
import type { SurveyAnswers } from './types';

const nativeStorage = vi.hoisted(() => ({
  getItem: vi.fn(),
  setItem: vi.fn(),
  removeItem: vi.fn(),
}));

vi.mock('@apps-in-toss/web-framework', () => ({ Storage: nativeStorage }));

const answers: SurveyAnswers = {
  skinType: 'normal',
  sensitivity: 'occasional',
  category: 'toner',
  primaryConcern: 'dryness',
  concerns: ['oil_control'],
  texture: 'lotion',
  finish: 'low_sticky',
  budget: 30_000,
  preferredIngredients: ['niacinamide'],
  preferredIngredientsText: '판테놀',
  avoidIngredients: ['salicylic acid', 'tea tree'],
  avoidIngredientsText: '향료, 에탄올',
  privacyConsent: true,
};

describe('buildStructuredProfile', () => {
  it('keeps each survey field separate from the natural-language query', () => {
    expect(buildStructuredProfile(answers)).toEqual({
      skin_type: 'normal',
      sensitivity_level: 'occasional',
      primary_concern: 'dryness',
      concerns: ['dryness', 'oil_control'],
      desired_categories: ['toner'],
      avoid_ingredients: ['salicylic acid', 'tea tree', '향료', '에탄올'],
      preferred_ingredients: ['niacinamide', '판테놀'],
      max_price_krw: 30_000,
      texture_preference: 'lotion',
      finish_preference: 'low_sticky',
    });
  });
});

describe('ingredientSelectionConflicts', () => {
  it('normalizes Korean ethanol and fragrance aliases', () => {
    expect(ingredientSelectionConflicts({
      ...answers,
      avoidIngredients: ['ethanol', 'fragrance'],
      avoidIngredientsText: '',
      preferredIngredients: [],
      preferredIngredientsText: '에탄올, parfum',
    })).toEqual(['에탄올', 'parfum']);
  });

  it('does not collapse broad alcohol or fatty alcohol into ethanol', () => {
    expect(ingredientSelectionConflicts({
      ...answers,
      avoidIngredients: ['ethanol', 'alcohol'],
      avoidIngredientsText: '',
      preferredIngredients: ['cetearyl alcohol'],
      preferredIngredientsText: '',
    })).toEqual([]);
  });

  it('normalizes niacinamide evidence aliases', () => {
    expect(ingredientSelectionConflicts({
      ...answers,
      avoidIngredients: ['niacinamide'],
      avoidIngredientsText: '',
      preferredIngredients: [],
      preferredIngredientsText: 'nicotinamide',
    })).toEqual(['nicotinamide']);
  });
});

describe('normalizeResponse', () => {
  it('normalizes the current API schema and resolves relative images', () => {
    const result = normalizeResponse({
      decision: 'recommend',
      ranking_policy: '추천 순위는 적합도와 데이터 신선도로 정하며 제휴 수수료는 반영하지 않아요.',
      grounded_explanation: 'A very long server explanation that should not be used as the heading.',
      results: [
        {
          score: 8.5,
          personalized_reason: '현재 조건에 맞는 추천이에요.',
          display_cautions: ['패치 테스트를 권장해요.'],
          display_matched_ingredients: ['판테놀'],
          product: {
            id: 'product-1',
            name: 'Barrier Toner',
            display_name_ko: '배리어 토너',
            brand: 'Example',
            category: 'toner',
            image_url: '/static/product.png',
            oliveyoung_price_krw: 19_000,
            purchase_url: 'https://shop.example.com/barrier-toner',
            retailer_name: 'Example Shop',
            catalog_source: 'open_beauty_facts',
            source_url: 'https://world.openbeautyfacts.org/product/123',
            source_updated_at: '2026-07-19',
            ingredient_status: 'complete',
            recommendation_tier: 'eligible',
            data_license: 'ODbL-1.0',
            external_links: [
              {
                kind: 'brand_official',
                label: 'Example 공식 제품 정보',
                provider: 'Example',
                url: 'https://brand.example.com/barrier-toner',
              },
              {
                kind: 'retailer',
                label: 'Unsafe retailer field',
                provider: 'Store',
                url: 'https://shop.example.com/barrier-toner',
              },
              {
                kind: 'ingredient_reference',
                label: 'Insecure source',
                provider: 'Source',
                url: 'http://source.example.com/barrier-toner',
              },
            ],
            ingredients: ['Panthenol'],
          },
        },
      ],
      product_source_status: { total_products: 4_250 },
    });

    expect(result.summary).toBe('선택한 조건을 바탕으로 제품 성분과 피부 적합도를 비교했어요.');
    expect(result.items[0].reason).toBe('현재 조건에 맞는 추천이에요.');
    expect(result.items[0].product.imageUrl).toBe(
      'https://k-beauty-recommendation-agent-gafd.onrender.com/static/product.png',
    );
    expect(result.items[0].product.purchaseUrl).toBe('https://shop.example.com/barrier-toner');
    expect(result.items[0].product.retailerName).toBe('Example Shop');
    expect(result.items[0].product.catalogSource).toBe('open_beauty_facts');
    expect(result.items[0].product.sourceUpdatedAt).toBe('2026-07-19');
    expect(result.items[0].product.externalLinks).toEqual([{
      kind: 'brand_official',
      label: 'Example 공식 제품 정보',
      provider: 'Example',
      url: 'https://brand.example.com/barrier-toner',
    }]);
    expect(result.items[0].product.offers).toEqual([]);
    expect(result.catalogTotal).toBe(4_250);
    expect(result.rankingPolicy).toBe('추천 순위는 적합도와 데이터 신선도로 정하며 제휴 수수료는 반영하지 않아요.');
    expect(result.additionalCandidates).toEqual([]);
  });

  it('keeps review provenance, reasons, ingredient evidence, and confidence factors', () => {
    const result = normalizeResponse({
      results: [{
        display_reasons: ['1순위 고민과 일치해요.', '최근 확인된 가격이 없어 최대 가격 조건을 확인할 수 없음'],
        missing_data: ['price'],
        data_confidence: {
          level: 'medium',
          label_ko: '근거 신뢰도 보통',
          factors: {
            ingredients: { status: 'verified', label_ko: '전체 성분표 확인' },
            product_source: {
              status: 'current',
              label_ko: '상품 정보 최근 확인',
              checked_at: '2026-07-20',
              date_kind: 'catalog_verified_at',
            },
            reviews: {
              status: 'current',
              label_ko: '리뷰 정보 최근 확인',
              checked_at: '2026-07-18',
              source_url: 'https://www.ulta.com/p/product-1',
            },
          },
        },
        product: {
          id: 'evidence-product',
          name: 'Evidence Serum',
          brand: 'Example',
          category: 'serum',
          ingredients: ['Panthenol'],
          claims: ['barrier support'],
          concerns: ['hydration'],
          texture_tags: ['lightweight'],
          review_source_url: 'https://www.ulta.com/p/product-1',
          review_verified_at: '2026-07-18',
          external_links: [{
            kind: 'review_reference',
            label: '리뷰 정보 · Ulta Beauty',
            provider: 'Ulta Beauty',
            url: 'https://www.ulta.com/p/product-1',
          }],
          ingredient_explanations: [{
            name: 'panthenol',
            label: 'Panthenol',
            display_name_ko: '판테놀',
            supports: ['hydration'],
            display_supports_ko: ['수분 보습'],
            cautions: [],
            display_cautions_ko: [],
            evidence_level: 'moderate',
            rationale: 'Supports hydration.',
            display_rationale_ko: '수분 유지에 도움을 줄 수 있어요.',
          }],
        },
      }],
    });

    expect(result.items[0].product).toEqual(expect.objectContaining({
      reviewSourceUrl: 'https://www.ulta.com/p/product-1',
      reviewVerifiedAt: '2026-07-18',
      claims: ['barrier support'],
      concerns: ['hydration'],
      textureTags: ['lightweight'],
    }));
    expect(result.items[0].product.ingredientExplanations[0]).toEqual(expect.objectContaining({
      name: 'panthenol',
      displayNameKo: '판테놀',
      evidenceLevel: 'moderate',
      displaySupportsKo: ['수분 보습'],
    }));
    expect(result.items[0].reasons).toEqual(['1순위 고민과 일치해요.']);
    expect(result.items[0].missingData).toEqual(['price']);
    expect(result.items[0].dataConfidence).toEqual({
      level: 'medium',
      labelKo: '근거 신뢰도 보통',
      factors: {
        ingredients: { status: 'verified', labelKo: '전체 성분표 확인' },
        productSource: {
          status: 'current',
          labelKo: '상품 정보 최근 확인',
          checkedAt: '2026-07-20',
          dateKind: 'catalog_verified_at',
          sourceUrl: undefined,
        },
        reviews: {
          status: 'current',
          labelKo: '리뷰 정보 최근 확인',
          checkedAt: '2026-07-18',
          dateKind: undefined,
          sourceUrl: 'https://www.ulta.com/p/product-1',
        },
      },
    });
  });

  it('drops a raw review URL unless it is present in verified external links', () => {
    const result = normalizeResponse({
      results: [{
        product: {
          id: 'unsafe-review-link',
          name: 'Safe Product',
          brand: 'Example',
          category: 'serum',
          ingredients: [],
          rating: 4.9,
          review_count: 9_999,
          review_source_url: 'https://evil.example/reviews',
          external_links: [{
            kind: 'ingredient_reference',
            label: '성분 정보 · INCIDecoder',
            provider: 'INCIDecoder',
            url: 'https://incidecoder.com/products/safe-product',
          }],
        },
      }],
    });

    expect(result.items[0].product.reviewSourceUrl).toBeUndefined();
    expect(result.items[0].product.rating).toBeUndefined();
    expect(result.items[0].product.reviewCount).toBeUndefined();
  });

  it('uses explicit additional candidates and removes duplicate primary entries', () => {
    const unknownPrice = {
      missing_data: ['price'],
      product: {
        id: 'unknown-price',
        name: 'Unknown Price Serum',
        brand: 'Example',
        category: 'serum',
        ingredients: [],
      },
    };
    const result = normalizeResponse({
      profile: { max_price_krw: 30_000 },
      results: [
        {
          product: {
            id: 'verified-price',
            name: 'Verified Price Serum',
            brand: 'Example',
            category: 'serum',
            ingredients: [],
          },
        },
        unknownPrice,
      ],
      additional_candidates: [unknownPrice],
    });

    expect(result.items.map((item) => item.product.id)).toEqual(['verified-price']);
    expect(result.additionalCandidates.map((item) => item.product.id)).toEqual(['unknown-price']);
  });

  it('separates missing-price results for a legacy budget response', () => {
    const result = normalizeResponse({
      profile: { max_price_krw: 30_000 },
      results: [
        {
          product: {
            id: 'verified-price',
            name: 'Verified Price Serum',
            brand: 'Example',
            category: 'serum',
            ingredients: [],
          },
        },
        {
          display_missing_data: ['가격'],
          product: {
            id: 'unknown-price',
            name: 'Unknown Price Serum',
            brand: 'Example',
            category: 'serum',
            ingredients: [],
          },
        },
      ],
    });

    expect(result.items.map((item) => item.product.id)).toEqual(['verified-price']);
    expect(result.additionalCandidates.map((item) => item.product.id)).toEqual(['unknown-price']);
  });

  it('keeps missing-price products in the main list when no price constraint exists', () => {
    const result = normalizeResponse({
      results: [{
        missing_data: ['price'],
        product: {
          id: 'no-budget',
          name: 'No Budget Serum',
          brand: 'Example',
          category: 'serum',
          ingredients: [],
        },
      }],
    });

    expect(result.items.map((item) => item.product.id)).toEqual(['no-budget']);
    expect(result.additionalCandidates).toEqual([]);
  });

  it('normalizes the v2 commerce summary without inventing a retailer destination', () => {
    const result = normalizeResponse({
      schema_version: 2,
      results: [
        {
          product: {
            id: 'v2-product',
            name: 'V2 Serum',
            brand: 'Example',
            category: 'serum',
            ingredients: [],
            source_url: 'https://catalog.example.com/v2-product',
            commerce: {
              offer_count: 3,
              retailer_count: 2,
              fresh_offer_count: 2,
              stale_offer_count: 1,
              best_current_price: { amount: 17_900, currency: 'KRW', retailer_name: 'Store A' },
              offers_url: '/api/v2/products/v2-product/offers',
            },
          },
        },
      ],
    });

    expect(result.items[0].product.commerce).toEqual({
      retailerCount: 2,
      offerCount: 3,
      freshOfferCount: 2,
      lowestFreshPriceKrw: 17_900,
      lowestFreshPriceCurrency: 'KRW',
      hasAffiliateOffers: false,
    });
    expect(result.items[0].product.offers).toEqual([]);
  });

  it('does not turn source or official URLs into legacy purchase offers', () => {
    const result = normalizeResponse({
      results: [{
        product: {
          id: 'information-only',
          name: 'Information Only',
          brand: 'Example',
          category: 'toner',
          ingredients: [],
          source_url: 'https://catalog.example.com/item',
          official_url: 'https://brand.example.com/item',
        },
      }],
    });

    expect(result.items[0].product.offers).toEqual([]);
  });

  it('prefers localized reasons over legacy mixed-language AI text', () => {
    const result = normalizeResponse({
      decision: 'recommend',
      results: [
        {
          ai_recommendation_explanation: 'Legacy mixed language reason.',
          display_reasons: ['요청한 제품군과 일치해요.', '예산 안에서 확인됐어요.'],
          product: {
            id: 'legacy-1',
            name: 'Legacy Sunscreen',
            brand: 'Legacy',
            category: 'sunscreen',
            ingredients: [],
          },
        },
      ],
    });

    expect(result.items[0].reason).toBe('요청한 제품군과 일치해요. · 예산 안에서 확인됐어요.');
  });

  it('removes legacy price diagnostics while keeping customer safety cautions', () => {
    const result = normalizeResponse({
      results: [{
        personalized_reason: '피부 고민에 맞는 성분을 포함해요. 다만 checked 가격 데이터가 없어 최대 가격 조건을 확인할 수 없음: ₩50,000',
        display_cautions: [
          'checked 가격 데이터가 없어 최대 가격 조건을 확인할 수 없음: ₩50,000',
          '민감 피부는 패치 테스트를 권장해요.',
        ],
        product: {
          id: 'clean-copy',
          name: 'Clean Copy Serum',
          brand: 'Example',
          category: 'serum',
          ingredients: [],
        },
      }],
    });

    expect(result.items[0].reason).toBe('피부 고민에 맞는 성분을 포함해요.');
    expect(result.items[0].cautions).toEqual(['민감 피부는 패치 테스트를 권장해요.']);
  });

  it('rejects malformed top-level responses', () => {
    expect(() => normalizeResponse(null)).toThrow('서버 응답 형식을 확인할 수 없어요.');
  });
});

describe('normalizeOffersResponse', () => {
  it('parses the v2 offer contract and keeps only the backend redirect URL', () => {
    const offers = normalizeOffersResponse({
      product_id: 'product-1',
      offers: [
        {
          id: 'offer-1',
          retailer: { id: 'retailer-1', name: 'Example Store' },
          price: { amount: 15_900, currency: 'KRW', status: 'current' },
          list_price: { amount: 19_900, currency: 'KRW', status: 'current' },
          stock_status: 'preorder',
          freshness: {
            status: 'fresh',
            checked_at: '2026-07-20T10:30:00Z',
          },
          redirect_url: '/r/signed-token',
          affiliate: {
            active: true,
            label: '광고·제휴',
            disclosure_ko: '구매 시 수수료를 받을 수 있어요.',
          },
        },
      ],
    });

    expect(offers).toEqual([{
      id: 'offer-1',
      retailerId: 'retailer-1',
      retailerName: 'Example Store',
      priceAmount: 15_900,
      listPriceAmount: 19_900,
      priceKrw: 15_900,
      listPriceKrw: 19_900,
      currency: 'KRW',
      availability: 'preorder',
      isStale: false,
      checkedAt: '2026-07-20T10:30:00Z',
      clickUrl: 'https://k-beauty-recommendation-agent-gafd.onrender.com/r/signed-token',
      isLinkOnly: false,
      isAffiliate: true,
      affiliateLabel: '광고·제휴',
      affiliateDisclosure: '구매 시 수수료를 받을 수 있어요.',
    }]);
  });

  it('marks expired data stale and rejects redirects outside the signed backend route', () => {
    const offers = normalizeOffersResponse({
      offers: [{
        id: 'stale-offer',
        retailer: { name: 'Old Store' },
        price: { amount: null, currency: 'KRW', status: 'stale' },
        stock_status: 'unknown',
        freshness: { status: 'stale', checked_at: '2026-07-01T00:00:00Z' },
        redirect_url: 'https://unsafe.example.com/product',
        affiliate: { active: false },
      }],
    });

    expect(offers[0]).toEqual(expect.objectContaining({
      priceKrw: undefined,
      availability: 'unknown',
      isStale: true,
      clickUrl: undefined,
      isAffiliate: false,
    }));
  });

  it('keeps a signed retailer destination for a link-only offer without showing a stale price', () => {
    const offers = normalizeOffersResponse({
      offers: [{
        id: 'oliveyoung-link',
        retailer: { name: 'Olive Young' },
        price: { amount: null, currency: 'KRW', status: 'stale' },
        stock_status: 'unknown',
        freshness: { status: 'stale', checked_at: '2026-05-01T00:00:00Z' },
        redirect_url: '/r/signed-link-only-token',
        link_only: true,
        affiliate: { active: false },
      }],
    });

    expect(offers[0]).toEqual(expect.objectContaining({
      retailerName: 'Olive Young',
      priceKrw: undefined,
      isStale: true,
      isLinkOnly: true,
      clickUrl: 'https://k-beauty-recommendation-agent-gafd.onrender.com/r/signed-link-only-token',
    }));
  });

  it('does not interpret a foreign-currency best price as KRW', () => {
    const result = normalizeResponse({
      results: [{
        product: {
          id: 'usd-product',
          name: 'USD Product',
          brand: 'Example',
          category: 'serum',
          ingredients: [],
          commerce: {
            offer_count: 1,
            retailer_count: 1,
            fresh_offer_count: 1,
            best_current_price: { amount: 1, currency: 'USD', retailer_name: 'Global Store' },
          },
        },
      }],
    });

    expect(result.items[0].product.commerce?.lowestFreshPriceKrw).toBeUndefined();
    expect(result.items[0].product.commerce?.lowestFreshPriceCurrency).toBe('USD');
  });
});

describe('anonymous session privacy', () => {
  let browserStorage: {
    getItem: ReturnType<typeof vi.fn>;
    setItem: ReturnType<typeof vi.fn>;
    removeItem: ReturnType<typeof vi.fn>;
  };
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    vi.resetModules();
    nativeStorage.getItem.mockReset().mockResolvedValue(null);
    nativeStorage.setItem.mockReset().mockResolvedValue(undefined);
    nativeStorage.removeItem.mockReset().mockResolvedValue(undefined);

    const stored = new Map<string, string>();
    browserStorage = {
      getItem: vi.fn((key: string) => stored.get(key) ?? null),
      setItem: vi.fn((key: string, value: string) => stored.set(key, value)),
      removeItem: vi.fn((key: string) => stored.delete(key)),
    };
    vi.stubGlobal('window', {
      localStorage: browserStorage,
      sessionStorage: {
        getItem: vi.fn(),
        setItem: vi.fn(),
        removeItem: vi.fn(),
      },
      setTimeout: globalThis.setTimeout,
      clearTimeout: globalThis.clearTimeout,
    });
    vi.stubGlobal('crypto', {
      getRandomValues: (value: Uint8Array) => {
        value.fill(7);
        return value;
      },
    });
    fetchMock = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ results: [] }),
    });
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('uses an ephemeral token and writes no storage when recommendation storage is declined', async () => {
    const { requestRecommendations } = await import('./api');

    await requestRecommendations({ ...answers, privacyConsent: false });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.headers).toEqual(expect.objectContaining({
      'X-KBeauty-Session': expect.stringMatching(/^kb_[a-f0-9]{48}$/),
    }));
    expect(JSON.parse(String(options.body))).toEqual(expect.objectContaining({
      privacy_consent: false,
      profile: expect.objectContaining({
        sensitivity_level: 'occasional',
        primary_concern: 'dryness',
        preferred_ingredients: ['niacinamide', '판테놀'],
      }),
    }));
    expect(nativeStorage.getItem).not.toHaveBeenCalled();
    expect(nativeStorage.setItem).not.toHaveBeenCalled();
    expect(browserStorage.getItem).not.toHaveBeenCalled();
    expect(browserStorage.setItem).not.toHaveBeenCalled();
  });

  it('creates a 30-day persistent token only when storage is accepted', async () => {
    const { requestRecommendations } = await import('./api');

    await requestRecommendations({ ...answers, privacyConsent: true });

    expect(nativeStorage.getItem).toHaveBeenCalledTimes(2);
    expect(nativeStorage.setItem).toHaveBeenCalledTimes(2);
    expect(browserStorage.setItem).toHaveBeenCalledTimes(2);
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(options.body)).privacy_consent).toBe(true);
  });

  it('does not create a persistent token while loading offers', async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: vi.fn().mockResolvedValue({ offers: [] }),
    });
    const { requestProductOffers } = await import('./api');

    await requestProductOffers('product-1');

    expect(nativeStorage.setItem).not.toHaveBeenCalled();
    expect(browserStorage.setItem).not.toHaveBeenCalled();
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options.headers).toBeUndefined();
  });

  it('deletes an existing stored session and clears both stores', async () => {
    const token = 'kb_1234567890abcdefghijklmnop';
    const issuedAt = String(Date.now());
    nativeStorage.getItem.mockImplementation((key: string) => Promise.resolve(
      key.includes('IssuedAt') ? issuedAt : token,
    ));
    const { deleteAnonymousSessionData } = await import('./api');

    await deleteAnonymousSessionData();

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(options).toEqual(expect.objectContaining({
      method: 'DELETE',
      headers: { 'X-KBeauty-Session': token },
    }));
    expect(nativeStorage.removeItem).toHaveBeenCalledTimes(2);
    expect(browserStorage.removeItem).toHaveBeenCalledTimes(2);
  });

  it('is safe when there is no stored session and does not call delete remotely', async () => {
    const { deleteAnonymousSessionData } = await import('./api');

    await deleteAnonymousSessionData();

    expect(fetchMock).not.toHaveBeenCalled();
    expect(nativeStorage.removeItem).toHaveBeenCalledTimes(2);
    expect(browserStorage.removeItem).toHaveBeenCalledTimes(2);
  });

  it('rejects aliased preferred and avoided ingredient conflicts before fetching', async () => {
    const { requestRecommendations } = await import('./api');

    await expect(requestRecommendations({
      ...answers,
      avoidIngredients: ['ethanol'],
      avoidIngredientsText: '',
      preferredIngredients: [],
      preferredIngredientsText: '에탄올',
    })).rejects.toThrow('선호 성분과 제외 성분이 겹쳐요: 에탄올');
    expect(fetchMock).not.toHaveBeenCalled();
    expect(nativeStorage.setItem).not.toHaveBeenCalled();
  });
});
