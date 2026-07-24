export type SkinType = 'oily' | 'dry' | 'combination' | 'normal' | 'unknown';

export type SensitivityLevel = 'frequent' | 'occasional' | 'low';

export type ProductCategory =
  | 'cleanser'
  | 'toner'
  | 'serum'
  | 'moisturizer'
  | 'sunscreen'
  | 'face_mask'
  | 'eye_care'
  | 'lip_care'
  | 'exfoliator'
  | 'body_cleanser'
  | 'body_moisturizer'
  | 'body_exfoliator'
  | 'shampoo'
  | 'conditioner'
  | 'hair_treatment'
  | 'base_makeup'
  | 'eye_makeup'
  | 'lip_makeup'
  | 'basic';

export interface SurveyAnswers {
  skinType: SkinType | '';
  sensitivity: SensitivityLevel | '';
  category: ProductCategory | '';
  primaryConcern: string;
  concerns: string[];
  texture: string;
  finish: string;
  budget: number | null;
  preferredIngredients: string[];
  preferredIngredientsText: string;
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
  linkType: 'product_page' | 'retailer_search';
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

export type VideoReviewStatus =
  | 'ready'
  | 'search_only'
  | 'no_results'
  | 'temporarily_unavailable'
  | 'quota_limited';

export interface ProductVideoReview {
  videoId: string;
  title: string;
  channelTitle: string;
  publishedAt?: string;
  duration?: string;
  thumbnailUrl?: string;
  viewCount?: number;
  likeCount?: number;
  channelId?: string;
  channelThumbnailUrl?: string;
  subscriberCount?: number;
  subscriberCountHidden: boolean;
  channelUrl?: string;
  url: string;
  hasPaidProductPlacement: boolean;
}

export interface ProductVideoReviews {
  provider: 'YouTube';
  status: VideoReviewStatus;
  query: string;
  searchUrl: string;
  messageKo: string;
  disclaimerKo: string;
  termsUrl: string;
  privacyUrl: string;
  videos: ProductVideoReview[];
}

export interface ProductExternalLink {
  kind: 'brand_official' | 'ingredient_reference' | 'data_reference' | 'review_reference';
  label: string;
  provider: string;
  url: string;
}

export interface IngredientExplanation {
  name: string;
  label: string;
  displayNameKo?: string;
  supports: string[];
  displaySupportsKo: string[];
  cautions: string[];
  displayCautionsKo: string[];
  evidenceLevel?: string;
  rationale?: string;
  displayRationaleKo?: string;
}

export interface DataConfidence {
  level: 'high' | 'medium' | 'low';
  labelKo: string;
  factors: {
    ingredients?: DataConfidenceFactor;
    productSource?: DataConfidenceFactor;
    reviews?: DataConfidenceFactor;
  };
}

export interface DataConfidenceFactor {
  status: string;
  labelKo: string;
  checkedAt?: string;
  dateKind?: string;
  sourceUrl?: string;
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
  reviewSourceUrl?: string;
  reviewVerifiedAt?: string;
  ingredients: string[];
  claims: string[];
  concerns: string[];
  textureTags: string[];
  ingredientExplanations: IngredientExplanation[];
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
  reasons: string[];
  cautions: string[];
  matchedIngredients: string[];
  missingData: string[];
  dataConfidence?: DataConfidence;
}

export interface RecommendationResult {
  decision: string;
  summary: string;
  items: RecommendationItem[];
  additionalCandidates: RecommendationItem[];
  catalogTotal?: number;
  rankingPolicy?: string;
}

export interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
  message?: string;
}
