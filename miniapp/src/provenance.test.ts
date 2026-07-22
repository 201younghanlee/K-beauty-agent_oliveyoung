import { describe, expect, it } from 'vitest';
import { hasVerifiedReviewMetrics, sourceUrlIsProductSource } from './provenance';
import type { Product } from './types';

function productWithSource(kind?: 'brand_official' | 'ingredient_reference' | 'data_reference'): Product {
  const sourceUrl = 'https://source.example.com/product';
  return {
    id: 'product',
    name: 'Product',
    brand: 'Brand',
    category: 'serum',
    sourceUrl,
    ingredients: [],
    claims: [],
    concerns: [],
    textureTags: [],
    ingredientExplanations: [],
    offers: [],
    externalLinks: kind ? [{ kind, provider: 'Source', label: 'Source', url: sourceUrl }] : [],
  };
}

describe('sourceUrlIsProductSource', () => {
  it('does not reclassify ingredient and data references as product sources', () => {
    expect(sourceUrlIsProductSource(productWithSource('ingredient_reference'))).toBe(false);
    expect(sourceUrlIsProductSource(productWithSource('data_reference'))).toBe(false);
  });

  it('keeps official and otherwise unclassified product URLs', () => {
    expect(sourceUrlIsProductSource(productWithSource('brand_official'))).toBe(true);
    expect(sourceUrlIsProductSource(productWithSource())).toBe(true);
  });
});

describe('hasVerifiedReviewMetrics', () => {
  it('hides legacy cached review numbers without a verified source', () => {
    const unsourced = { ...productWithSource(), rating: 4.9, reviewCount: 2_000 };
    const sourced = { ...unsourced, reviewSourceUrl: 'https://www.ulta.com/p/product' };

    expect(hasVerifiedReviewMetrics(unsourced)).toBe(false);
    expect(hasVerifiedReviewMetrics(sourced)).toBe(true);
  });
});
