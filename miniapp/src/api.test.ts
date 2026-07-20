import { describe, expect, it } from 'vitest';
import { buildStructuredProfile, normalizeResponse } from './api';
import type { SurveyAnswers } from './types';

const answers: SurveyAnswers = {
  skinType: 'normal',
  category: 'toner',
  concerns: ['dryness', 'oil_control'],
  texture: '',
  budget: 30_000,
  avoidIngredients: ['salicylic acid', 'tea tree'],
  avoidIngredientsText: '향료, 에탄올',
};

describe('buildStructuredProfile', () => {
  it('keeps each survey field separate from the natural-language query', () => {
    expect(buildStructuredProfile(answers)).toEqual({
      skin_type: 'normal',
      concerns: ['dryness', 'oil_control'],
      desired_categories: ['toner'],
      avoid_ingredients: ['salicylic acid', 'tea tree', '향료', '에탄올'],
      max_price_krw: 30_000,
    });
  });
});

describe('normalizeResponse', () => {
  it('normalizes the current API schema and resolves relative images', () => {
    const result = normalizeResponse({
      decision: 'recommend',
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
    expect(result.catalogTotal).toBe(4_250);
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

  it('rejects malformed top-level responses', () => {
    expect(() => normalizeResponse(null)).toThrow('서버 응답 형식을 확인할 수 없어요.');
  });
});
