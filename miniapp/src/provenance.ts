import type { Product } from './types';

/** Keep a raw source URL in the product-source group only when it is not
 * already classified as an ingredient or data reference. */
export function sourceUrlIsProductSource(product: Product): boolean {
  if (!product.sourceUrl) {
    return false;
  }
  let normalized: string;
  try {
    normalized = new URL(product.sourceUrl).toString();
  } catch {
    return false;
  }
  const classifiedLink = product.externalLinks?.find((link) => link.url === normalized);
  return !classifiedLink || classifiedLink.kind === 'brand_official';
}

export function hasVerifiedReviewMetrics(product: Product): boolean {
  return Boolean(
    product.reviewSourceUrl
    && (product.rating !== undefined || product.reviewCount !== undefined),
  );
}
