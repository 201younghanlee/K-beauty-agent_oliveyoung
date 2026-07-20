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
}

export interface ApiErrorBody {
  detail?: string | Array<{ msg?: string }>;
  message?: string;
}
