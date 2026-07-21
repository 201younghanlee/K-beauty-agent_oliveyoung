export type SkinType = 'oily' | 'dry' | 'combination' | 'sensitive' | 'normal';

export type ProductCategory = 'cleanser' | 'toner' | 'serum' | 'moisturizer' | 'sunscreen';

export interface SurveyAnswers {
  skinType: SkinType | '';
  category: ProductCategory | '';
  concerns: string[];
  texture: string;
  budget: number | null;
  avoidIngredients: string[];
  avoidIngredientsText: string;
  privacyConsent: boolean;
}

export type OfferAvailability = 'in_stock' | 'preorder' | 'out_of_stock' | 'unknown';

export interface RetailOffer {
  id: string;
  retailerId?: string;
  retailerName: string;
  priceAmount?: number;
  listPriceAmount?: number;
  priceKrw?: number;
  listPriceKrw?: number;
  currency: string;
  availability: OfferAvailability;
  isStale: boolean;
  checkedAt?: string;
  clickUrl?: string;
  isLinkOnly: boolean;
  isAffiliate: boolean;
  affiliateLabel?: string;
  affiliateDisclosure?: string;
}

export interface CommerceSummary {
  retailerCount: number;
  offerCount: number;
  freshOfferCount: number;
  lowestFreshPriceKrw?: number;
  lowestFreshPriceCurrency?: string;
  hasAffiliateOffers: boolean;
}

export interface ProductExternalLink {
  kind: 'brand_official' | 'ingredient_reference' | 'data_reference';
  label: string;
  provider: string;
  url: string;
}

export interface Product {
  id: string;
  name: string;
  displayNameKo?: string;
  brand: string;
  category: string;
  imageUrl?: string;
  oliveyoungUrl?: string;
  purchaseUrl?: string;
  sourceUrl?: string;
  officialUrl?: string;
  retailerName?: string;
  priceKrw?: number;
  priceCheckedAt?: string;
  rating?: number;
  reviewCount?: number;
  reviewSummary?: string;
  ingredients: string[];
  catalogSource?: string;
  sourceUpdatedAt?: string;
  ingredientStatus?: string;
  recommendationTier?: string;
  dataLicense?: string;
  dataAttributionUrl?: string;
  externalLinks?: ProductExternalLink[];
  commerce?: CommerceSummary;
  offers: RetailOffer[];
}

export interface RecommendationItem {
  product: Product;
  score?: number;
  reason: string;
  cautions: string[];
  matchedIngredients: string[];
}

export interface RecommendationResult {
  decision: string;
  summary: string;
  items: RecommendationItem[];
  catalogTotal?: number;
  rankingPolicy?: string;
}

export interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
  message?: string;
}
