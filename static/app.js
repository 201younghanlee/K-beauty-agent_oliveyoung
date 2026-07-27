const LANGUAGE_STORAGE_KEY = "kBeautyAgentLanguage";
const SESSION_STORAGE_KEY = "kBeautyAgentAnonymousSessionV1";
const SESSION_ISSUED_AT_KEY = "kBeautyAgentAnonymousSessionIssuedAtV1";
const SESSION_PATTERN = /^[A-Za-z0-9_-]{20,128}$/;
const SESSION_MAX_AGE_MS = 30 * 24 * 60 * 60 * 1000;
// The public web client is served from the API origin. Cross-origin static
// previews must opt in through a dedicated origin instead of silently sending
// anonymous session tokens from the shared github.io origin.
const API_BASE_URL = "";

let memorySessionToken = "";
let memorySessionIssuedAt = 0;

const state = {
  lang: readStoredLanguage(),
  recommendationId: null,
  profile: {},
  productsById: new Map(),
  offerRequests: new Map(),
  activeOfferProductId: null,
  allProducts: [],
  currentResults: [],
  routineSelectedIds: new Set(),
  routineKnownSavedIds: new Set(),
  selections: { saved_ids: [], compare_ids: [], saved_products: [], compare_products: [], total_cost_krw: 0 },
};

const uiText = {
  ko: {
    statusIdle: "퀴즈를 제출하면 3-5개의 추천 카드가 여기에 표시됩니다.",
    profileEmpty: "세션 프로필이 아직 없습니다.",
    submitStatus: "피부 타입, 성분, 예산을 분석하는 중...",
    followUpStatus: "후속 조건을 반영하는 중...",
    requestFailed: "추천 요청에 실패했습니다.",
    complete: "추천 완료",
    followUpComplete: "후속 조건 반영",
    resultCount: "추천 결과 {count}개",
    followUpResultCount: "후속 조건을 반영한 추천 {count}개",
    backendConnectionFailed: "백엔드 서버 연결에 실패했습니다. Render 서비스가 실행 중인지 확인해 주세요.",
    criteriaReset: "검색 기준을 초기화했습니다.",
    noCurrentResults: "먼저 추천 결과를 받아주세요.",
    allCompareAdded: "현재 추천 제품 {count}개를 비교에 추가했습니다.",
    allRoutineAdded: "현재 추천 제품 {count}개를 루틴에 담았습니다.",
    criteriaTitle: "검색 기준",
    recommendationGuide: "추천 카드는 사용자 조건과 제품 근거의 적합도를 기준으로 정렬되며, 카드 안의 중요 성분은 추천 근거에서 중요한 순서로 표시됩니다.",
    reset: "세션이 초기화되었습니다.",
    noReason: "추천 이유 데이터가 아직 없습니다.",
    noReview: "리뷰 요약 데이터가 아직 없습니다.",
    noReviewShort: "리뷰 요약 없음",
    actualReviews: "선별 실제 리뷰",
    positiveReview: "좋았다는 리뷰",
    negativeReview: "아쉬웠다는 리뷰",
    reviewSource: "리뷰 출처",
    noSkinFit: "피부 적합도 데이터 없음",
    needPrice: "가격 확인 필요",
    noSpecialCaution: "특별 주의 데이터 없음",
    compareAdd: "비교 추가",
    routineAdd: "루틴 담기",
    selected: "선택됨",
    saved: "저장됨",
    save: "저장",
    compare: "비교",
    remove: "삭제",
    oliveyoung: "올리브영",
    official: "브랜드 공식몰",
    productSource: "제품 데이터 출처",
    catalogNoticeTitle: "카탈로그 데이터 안내",
    catalogNotice: "Open Beauty Facts의 최근 3년 내 수정 기록만 사용하지만, 수정일은 현재 판매·포뮬러 확인일이 아닙니다. 개별 상품명·이미지·전성분은 오래됐거나 누락될 수 있고, 민감 피부·제외 성분 조건에서는 이 상품을 추천에서 배제합니다. 가격·재고와 현재 포장은 판매처에서 다시 확인해 주세요.",
    buyLink: "구매 링크",
    recommendedReason: "추천 이유",
    ingredients: "중요 성분",
    review: "리뷰",
    combo: "추천 조합",
    cost: "가격",
    skinCompatibility: "피부 적합도",
    ingredient: "성분",
    compareStandard: "비교 기준",
    image: "이미지",
    verifiedDate: "기준일",
    officialImage: "공식 이미지",
    hwahaeImage: "화해 이미지",
    glowpickImage: "글로우픽 이미지",
    openBeautyFactsImage: "Open Beauty Facts 이미지",
    oliveyoungSnapshotImage: "올리브영 스냅샷 이미지",
    retailerImage: "리테일러 이미지",
    imageMissing: "이미지 없음",
    modalTitle: "성분",
    evidenceLevel: "근거 수준",
    supportConcerns: "도움 고민",
    suitableSkin: "적합 피부",
    caution: "주의",
    compareEmpty: "비교로 선택한 제품들이 여기에 모입니다.",
    routineEmpty: "저장한 제품이 장바구니 형식으로 표시됩니다.",
    total: "총액",
    selectedTotal: "선택 제품 총액",
    blockedIngredients: "차단 성분",
    selectAll: "전체 선택",
    deselectAll: "전체 해제",
    clearAll: "전체 삭제",
    compareSelected: "선택 제품 비교",
    budgetNone: "제한 없음",
    compareRetailers: "판매처·쇼핑 검색",
    offerModalTitle: "직접 상품 페이지와 검색 결과",
    offerLoading: "최신 판매처 정보를 확인하는 중입니다...",
    offerLoadFailed: "판매처 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
    offerEmpty: "현재 비교할 수 있는 판매처 정보가 없습니다.",
    lowestPrice: "최저 {price}",
    legacyPrice: "판매가 {price}",
    retailerCount: "판매처 {count}곳",
    freshRetailerCount: "최신 판매처 {count}곳",
    freshPrice: "최신 가격",
    stalePrice: "오래된 가격",
    unknownFreshness: "확인 시점 미상",
    checkedAt: "확인 {date}",
    stockIn: "재고 있음",
    stockOut: "품절",
    stockPreorder: "예약판매",
    stockUnknown: "재고 정보 미제공",
    affiliateBadge: "광고·제휴",
    affiliateTitle: "광고·제휴 안내",
    affiliateDisclosure: "이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.",
    goToRetailer: "판매처에서 확인",
    searchAtRetailer: "{retailer}에서 한국어로 검색",
    searchAtRetailerEnglish: "{retailer}에서 영문으로 검색",
    retailerSearchBadge: "한국어 상품 검색",
    retailerSearchBadgeEnglish: "영문 상품 검색",
    retailerSearchPrice: "검색 결과에서 가격 확인",
    retailerSearchNote: "한국어 검색 결과에서 정확한 상품인지와 실제 판매 여부·가격·재고를 확인해 주세요.",
    retailerSearchNoteEnglish: "영문 검색 결과에서 정확한 상품인지와 실제 판매 여부·가격·재고를 확인해 주세요.",
    noTrackedLink: "안전한 구매 링크 미제공",
    listPrice: "정가 {price}",
    offerSummaryUnknown: "판매처에서 현재 가격과 재고를 다시 확인해 주세요.",
  },
  en: {
    statusIdle: "Submit the quiz to see 3-5 recommendation cards here.",
    profileEmpty: "No session profile yet.",
    submitStatus: "Analyzing skin type, ingredients, and budget...",
    followUpStatus: "Applying follow-up conditions...",
    requestFailed: "Recommendation request failed.",
    complete: "Recommendation complete",
    followUpComplete: "Follow-up applied",
    resultCount: "{count} recommendations",
    followUpResultCount: "{count} recommendations after follow-up",
    backendConnectionFailed: "Could not connect to the backend server. Please check that the Render service is running.",
    criteriaReset: "Search criteria have been reset.",
    noCurrentResults: "Get recommendations first.",
    allCompareAdded: "Added {count} current recommendations to compare.",
    allRoutineAdded: "Added {count} current recommendations to routine.",
    criteriaTitle: "Search criteria",
    recommendationGuide: "Recommendation cards are ordered by fit to your criteria. Key ingredients inside each card are shown in order of recommendation importance.",
    reset: "Session has been reset.",
    noReason: "No recommendation rationale yet.",
    noReview: "No review summary yet.",
    noReviewShort: "No review summary",
    actualReviews: "Selected actual reviews",
    positiveReview: "Positive review",
    negativeReview: "Critical review",
    reviewSource: "Review source",
    noSkinFit: "No skin compatibility data",
    needPrice: "Price check needed",
    noSpecialCaution: "No special caution data",
    compareAdd: "Add to compare",
    routineAdd: "Add to routine",
    selected: "Selected",
    saved: "Saved",
    save: "Save",
    compare: "Compare",
    remove: "Remove",
    oliveyoung: "Olive Young",
    official: "Official",
    productSource: "Product data source",
    catalogNoticeTitle: "Catalog data notice",
    catalogNotice: "Only Open Beauty Facts records edited within the last three years are used, but an edit date is not a current-sale or formula check. Community records may still be incomplete or incorrect and are excluded for sensitive-skin and avoid-ingredient requests. Confirm current packaging, price, and stock with a retailer.",
    buyLink: "Purchase link",
    recommendedReason: "Why recommended",
    ingredients: "Key ingredients",
    review: "Review",
    combo: "Recommended combination",
    cost: "Cost",
    skinCompatibility: "Skin compatibility",
    ingredient: "Ingredients",
    compareStandard: "Compare by",
    image: "Image",
    verifiedDate: "Verified",
    officialImage: "Official image",
    hwahaeImage: "Hwahae image",
    glowpickImage: "Glowpick image",
    openBeautyFactsImage: "Open Beauty Facts image",
    oliveyoungSnapshotImage: "Olive Young snapshot image",
    retailerImage: "Retailer image",
    imageMissing: "No image",
    modalTitle: "Ingredient",
    evidenceLevel: "Evidence level",
    supportConcerns: "Supports",
    suitableSkin: "Suitable for",
    caution: "Caution",
    compareEmpty: "Products selected for comparison will appear here.",
    routineEmpty: "Saved products will appear as a routine cart.",
    total: "Total",
    selectedTotal: "Selected total",
    blockedIngredients: "Blocked ingredients",
    selectAll: "Select all",
    deselectAll: "Deselect all",
    clearAll: "Clear all",
    compareSelected: "Compare selected",
    budgetNone: "No limit",
    compareRetailers: "Retailers and shopping search",
    offerModalTitle: "Direct product pages and search results",
    offerLoading: "Checking the latest retailer information...",
    offerLoadFailed: "Could not load retailer information. Please try again shortly.",
    offerEmpty: "There are no retailer offers available to compare right now.",
    lowestPrice: "From {price}",
    legacyPrice: "Listed at {price}",
    retailerCount: "{count} retailers",
    freshRetailerCount: "{count} current retailers",
    freshPrice: "Current price",
    stalePrice: "Stale price",
    unknownFreshness: "Check time unknown",
    checkedAt: "Checked {date}",
    stockIn: "In stock",
    stockOut: "Out of stock",
    stockPreorder: "Pre-order",
    stockUnknown: "Stock not provided",
    affiliateBadge: "Ad · affiliate",
    affiliateTitle: "Ad and affiliate disclosure",
    affiliateDisclosure: "We may earn a commission when you purchase through some retailer links. Affiliate status and commission do not affect recommendation ranking.",
    goToRetailer: "Check at retailer",
    searchAtRetailer: "Search at {retailer}",
    searchAtRetailerEnglish: "Search at {retailer}",
    retailerSearchBadge: "Product search",
    retailerSearchBadgeEnglish: "English product search",
    retailerSearchPrice: "Check price in search results",
    retailerSearchNote: "Confirm the exact product, availability, price, and stock in the search results.",
    retailerSearchNoteEnglish: "Confirm the exact product, availability, price, and stock in the English search results.",
    noTrackedLink: "Secure purchase link unavailable",
    listPrice: "List {price}",
    offerSummaryUnknown: "Confirm the current price and stock with the retailer.",
  },
};

const labels = {
  ko: {
    skin_type: "피부 타입",
    concerns: "고민",
    desired_categories: "제품군",
    preferred_ingredients: "선호 성분",
    max_price_krw: "예산",
    min_price_krw: "최소 가격",
    texture_preference: "제형",
    allergies: "알러지",
    avoid_ingredients: "피해야 할 성분",
  },
  en: {
    skin_type: "Skin type",
    concerns: "Concerns",
    desired_categories: "Product type",
    preferred_ingredients: "Preferred ingredients",
    max_price_krw: "Budget",
    min_price_krw: "Minimum price",
    texture_preference: "Texture",
    allergies: "Allergies",
    avoid_ingredients: "Avoid ingredients",
  },
};

const valueLabels = {
  ko: {
    oily: "지성",
    dry: "건성",
    combination: "복합성",
    sensitive: "민감성",
    normal: "보통",
    oil_control: "유분",
    acne: "트러블",
    clogged_pores: "막힌 모공",
    hydration: "수분",
    barrier_support: "장벽",
    redness: "홍조",
    hyperpigmentation: "잡티",
    dryness: "건조",
    pores: "모공",
    cleanser: "클렌저",
    toner: "토너",
    serum: "세럼",
    moisturizer: "수분크림",
    sunscreen: "선크림",
    face_mask: "마스크팩",
    eye_care: "아이케어",
    lip_care: "립케어",
    exfoliator: "각질 케어",
    body_cleanser: "바디워시",
    body_moisturizer: "바디 보습",
    body_exfoliator: "바디 각질 케어",
    shampoo: "샴푸",
    conditioner: "컨디셔너",
    hair_treatment: "헤어 트리트먼트",
    base_makeup: "베이스 메이크업",
    eye_makeup: "아이 메이크업",
    lip_makeup: "립 메이크업",
    basic: "기초 루틴",
    dewy: "촉촉",
    lightweight: "산뜻",
    rich: "꾸덕",
    gel: "젤",
    niacinamide: "나이아신아마이드",
    "salicylic acid": "살리실산/BHA",
    "green tea extract": "녹차 추출물",
    panthenol: "판테놀",
    "ceramide np": "세라마이드",
    glycerin: "글리세린",
    "hyaluronic acid": "히알루론산",
    "centella asiatica": "병풀/시카",
    "houttuynia cordata": "어성초",
    "houttuynia cordata extract": "어성초 추출물",
    water: "정제수",
    "cocamidopropyl betaine": "코카미도프로필베타인",
    "sodium lauroyl methyl isethionate": "소듐라우로일메틸이세티오네이트",
    "butylene glycol": "부틸렌글라이콜",
    "tea tree leaf oil": "티트리잎오일",
    allantoin: "알란토인",
    "betaine salicylate": "베타인살리실레이트",
    "citric acid": "시트릭애씨드",
    betaine: "베타인",
    "portulaca oleracea extract": "쇠비름 추출물",
    madecassoside: "마데카소사이드",
    "shea butter": "시어버터",
    "sunflower seed oil": "해바라기씨오일",
    "sodium hyaluronate": "소듐하이알루로네이트",
    "snail secretion filtrate": "달팽이 점액 여과물",
    "rice extract": "쌀 추출물",
    "probiotic ferment": "프로바이오틱 발효물",
    squalane: "스쿠알란",
    "rice bran extract": "쌀겨 추출물",
    "calendula extract": "카렌듈라 추출물",
    "papaya extract": "파파야 추출물",
    "sea buckthorn extract": "비타민나무 추출물",
    fragrance: "향료",
    alcohol: "알코올",
    snail: "달팽이",
    "tea tree": "티트리",
    propolis: "프로폴리스",
    "tranexamic acid": "트라넥사믹애씨드",
    arbutin: "알부틴",
    "ascorbic acid": "비타민 C",
    "zinc oxide": "징크옥사이드",
    "onion extract": "양파 추출물",
    mugwort: "쑥",
    honey: "꿀",
    ginseng: "인삼",
    "bifida ferment": "비피다 발효물",
    "lactobacillus ferment": "락토바실러스 발효물",
    "glutathione": "글루타치온",
  },
  en: {
    oily: "oily",
    dry: "dry",
    combination: "combination",
    sensitive: "sensitive",
    normal: "normal",
    oil_control: "oil control",
    acne: "acne",
    clogged_pores: "clogged pores",
    hydration: "hydration",
    barrier_support: "barrier support",
    redness: "redness",
    hyperpigmentation: "dark spots",
    dryness: "dryness",
    pores: "pores",
    cleanser: "cleanser",
    toner: "toner",
    serum: "serum",
    moisturizer: "moisturizer",
    sunscreen: "sunscreen",
    face_mask: "face mask",
    eye_care: "eye care",
    lip_care: "lip care",
    exfoliator: "exfoliator",
    body_cleanser: "body wash",
    body_moisturizer: "body moisturizer",
    body_exfoliator: "body exfoliator",
    shampoo: "shampoo",
    conditioner: "conditioner",
    hair_treatment: "hair treatment",
    base_makeup: "base makeup",
    eye_makeup: "eye makeup",
    lip_makeup: "lip makeup",
    basic: "basic routine",
    dewy: "dewy",
    lightweight: "lightweight",
    rich: "rich",
    gel: "gel",
    niacinamide: "niacinamide",
    "salicylic acid": "salicylic acid / BHA",
    "green tea extract": "green tea extract",
    panthenol: "panthenol",
    "ceramide np": "ceramide NP",
    glycerin: "glycerin",
    "hyaluronic acid": "hyaluronic acid",
    "centella asiatica": "centella asiatica / cica",
    fragrance: "fragrance",
    alcohol: "alcohol",
    snail: "snail",
    "tea tree": "tea tree",
    "rice extract": "rice extract",
    propolis: "propolis",
    "tranexamic acid": "tranexamic acid",
    arbutin: "arbutin",
    "ascorbic acid": "vitamin C",
    "zinc oxide": "zinc oxide",
    "onion extract": "onion extract",
    mugwort: "mugwort",
    honey: "honey",
    ginseng: "ginseng",
    "bifida ferment": "bifida ferment",
    "lactobacillus ferment": "lactobacillus ferment",
    "houttuynia cordata": "houttuynia cordata",
    madecassoside: "madecassoside",
    glutathione: "glutathione",
  },
};

function text(key) {
  return uiText[state.lang]?.[key] || uiText.ko[key] || key;
}

function setLanguage(lang) {
  state.lang = lang === "en" ? "en" : "ko";
  storeLanguage(state.lang);
  applyLanguage();
  updateBudgetLabel();
  renderProfile(state.profile);
  renderRoutine();
  renderCompareSummary();
  renderCatalogs();
  if (state.selections.compare_products?.length) renderCompareTable();
  if (state.activeOfferProductId) renderOfferModal(state.productsById.get(state.activeOfferProductId));
  if (window.lucide) window.lucide.createIcons();
}

function readStoredLanguage() {
  try {
    return window.localStorage?.getItem(LANGUAGE_STORAGE_KEY) === "en" ? "en" : "ko";
  } catch {
    return "ko";
  }
}

function storeLanguage(lang) {
  try {
    window.localStorage?.setItem(LANGUAGE_STORAGE_KEY, lang);
  } catch {
    // Language persistence is a convenience; private browsing/storage blocks should not break the app.
  }
}

function applyLanguage() {
  document.documentElement.lang = state.lang;
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.classList.toggle("active", button.dataset.lang === state.lang);
  });
  applyStaticLanguage();
}

function applyStaticLanguage() {
  const en = state.lang === "en";
  setTextAny([".nav-link[href='/#hero']", ".nav-link[href='./#hero']"], en ? "Home" : "홈");
  setTextAny([".nav-link[href='/#quiz']", ".nav-link[href='./#quiz']"], en ? "Skin Quiz" : "피부 퀴즈");
  setTextAny([".nav-link[href='/#recommendation']", ".nav-link[href='./#recommendation']"], en ? "Recommendations" : "추천");
  setTextAny([".nav-link[href='/compare']", ".nav-link[href='./#compare']"], en ? "Product Compare" : "제품 비교");
  setTextAny([".nav-link[href='/routine']", ".nav-link[href='./#routine']"], en ? "Personal Routine" : "개인 루틴");
  setText(".hero-copy .eyebrow", en ? "K-beauty agent for ingredients and budget" : "성분과 예산을 함께 보는 K-뷰티 에이전트");
  setText(".hero-cta-wrap > span", en ? "Reflects skin type, ingredients to avoid, and budget in about 30 seconds." : "30초 안에 피부 타입, 제외 성분, 예산을 반영합니다.");
  setText("#quiz .mini-label", en ? "Skin Quiz" : "피부 퀴즈");
  setText("#quiz h2", en ? "Choose your skin and buying conditions" : "피부와 구매 조건을 선택해 주세요");
  setText("#recommendation .mini-label", en ? "Recommendations" : "추천 결과");
  setText("#recommendation h2", en ? "Recommended products and reasons" : "추천 제품과 선택 이유");
  setText("#compare .mini-label", en ? "Product Compare" : "제품 비교");
  setText("#compare h2", en ? "Compare selected products" : "선택한 제품 비교");
  setText("#compareSelected span", text("compareSelected"));
  setText("#compareClearAll span", text("clearAll"));
  setText("#compare .catalog-title .mini-label", en ? "All Products" : "전체 상품");
  setText("#compare .catalog-title h2", en ? "Choose products to compare" : "비교할 제품을 선택하세요");
  setText("#routine .mini-label", en ? "Personal Routine" : "개인 루틴");
  setText("#routine h2", en ? "Saved product cart" : "저장한 제품 장바구니");
  setTotalLabel();
  setText("#routine .catalog-title .mini-label", en ? "All Products" : "전체 상품");
  setText("#routine .catalog-title h2", en ? "Choose products for your routine" : "루틴에 담을 제품을 선택하세요");
  setText("#status", text("statusIdle"));
  setText(".criteria-title", text("criteriaTitle"));
  setText("#recommendationGuide", text("recommendationGuide"));
  setText("#catalogNoticeTitle", text("catalogNoticeTitle"));
  setText("#catalogNoticeText", text("catalogNotice"));
  setText("#ingredientModalTitle", text("modalTitle"));
  setText("#affiliateDisclosure strong", text("affiliateTitle"));
  setText("#affiliateDisclosure p", text("affiliateDisclosure"));
  setText("#offerModalEyebrow", text("compareRetailers"));
  setText("#offerModalTitle", text("offerModalTitle"));

  setLegend(0, en ? "Skin type" : "피부 타입");
  setLegend(1, en ? "Product type" : "제품 타입");
  setLegend(2, en ? "Main concern" : "주요 고민");
  setLegend(3, en ? "Texture preference" : "선호 제형");
  setLegend(4, en ? "Budget and ingredients to avoid" : "예산과 제외 성분");
  setText("label[for='budget']", en ? "Max budget" : "최대 예산");
  setText(".text-field span", en ? "Ingredients to avoid" : "피하고 싶은 성분");
  setText(
    "[data-form-ranking-note]",
    en
      ? "Hair and makeup forms are compared by product form, sensitivity, excluded ingredients, and data provenance rather than a facial-concern score."
      : "헤어·메이크업은 피부 고민 점수 대신 제품 형태, 민감도, 제외 성분과 데이터 출처를 중심으로 비교합니다.",
  );
  const privacyCopy = document.querySelector(".privacy-consent > span");
  const privacyLink = document.querySelector("#privacyPolicyLink");
  if (privacyCopy && privacyLink) {
    privacyCopy.textContent = en
      ? "I agree that a controlled profile made from my skin selections and ingredients to avoid may be processed for personalized recommendations for up to 30 days. "
      : "맞춤 추천을 위해 선택한 피부 정보와 피해야 할 성분으로 만든 통제 프로필을 최대 30일간 처리하는 데 동의합니다. ";
    privacyLink.textContent = en ? "Privacy notice" : "개인정보 처리 안내";
    privacyLink.href = apiUrl("/privacy");
    privacyCopy.append(privacyLink);
  }
  setText("#quizForm button[type='submit'] span", en ? "Get recommendations" : "추천 받기");
  setText("#followUpForm button span", en ? "Apply" : "반영");
  setPlaceholder("#allergyInput", en ? "e.g. fragrance, snail, alcohol, hyaluronic acid" : "예: 향료, 달팽이, 알코올, 히알루론산");
  setPlaceholder("#followUpQuery", en ? "Add follow-up conditions: e.g. under ₩20,000 with niacinamide" : "후속 조건 추가: 예) 나이아신아마이드 들어간 2만원 이하 제품");

  setBudgetOptions(en);
  setChoiceLabels(en);
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = value;
}

function setTextAny(selectors, value) {
  selectors.forEach((selector) => setText(selector, value));
}

function setPlaceholder(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.placeholder = value;
}

function setLegend(index, value) {
  const legend = document.querySelectorAll("legend")[index];
  if (legend) legend.textContent = value;
}

function setTotalLabel() {
  setText("[data-total-label]", text("total"));
  setText("[data-selected-total-label]", text("selectedTotal"));
}

function setBudgetOptions(en) {
  const options = [...document.querySelectorAll("#budget option")];
  const labels = en
    ? ["No price limit", "Under ₩10,000", "Under ₩20,000", "Under ₩30,000", "Under ₩40,000", "Under ₩50,000", "Under ₩60,000"]
    : ["가격 선택 안함", "₩10,000 이하", "₩20,000 이하", "₩30,000 이하", "₩40,000 이하", "₩50,000 이하", "₩60,000 이하"];
  options.forEach((option, index) => {
    option.textContent = labels[index] || option.textContent;
  });
}

function setChoiceLabels(en) {
  const labels = {
    skinType: en ? ["Oily", "Dry", "Combination", "Sensitive", "No selection"] : ["지성", "건성", "복합성", "민감성", "선택 안함"],
    productType: en
      ? [
          "Cleanser / foam",
          "Cleansing oil",
          "Toner / skin",
          "Toner pad",
          "Mist",
          "Serum / ampoule",
          "Essence",
          "Moisturizer",
          "Lotion / emulsion",
          "Sunscreen",
          "Face mask",
          "Eye care",
          "Lip care",
          "Face exfoliator",
          "Body wash",
          "Body moisturizer",
          "Body exfoliator",
          "Shampoo",
          "Conditioner",
          "Hair mask / treatment",
          "Base makeup",
          "Eye makeup",
          "Lip makeup",
          "Basic routine",
          "No selection",
        ]
      : [
          "클렌저/폼",
          "클렌징오일",
          "토너/스킨",
          "토너패드",
          "미스트",
          "세럼/앰플",
          "에센스",
          "수분크림",
          "로션/에멀전",
          "선크림",
          "마스크팩",
          "아이케어",
          "립케어",
          "얼굴 각질케어",
          "바디워시",
          "바디 보습",
          "바디 각질케어",
          "샴푸",
          "컨디셔너",
          "헤어팩/트리트먼트",
          "베이스 메이크업",
          "아이 메이크업",
          "립 메이크업",
          "기초 루틴",
          "선택 안함",
        ],
    mainConcern: en ? ["Acne", "Oil", "Hydration", "Barrier", "Redness", "Dark spots", "Pores", "No selection"] : ["트러블", "유분", "수분", "장벽", "홍조", "잡티", "모공", "선택 안함"],
    texture: en ? ["Dewy", "Lightweight", "Rich", "Gel", "No selection"] : ["촉촉", "산뜻", "꾸덕", "젤", "선택 안함"],
  };
  Object.entries(labels).forEach(([name, values]) => {
    document.querySelectorAll(`input[name="${name}"]`).forEach((input, index) => {
      const label = input.closest("label");
      if (!label) return;
      [...label.childNodes].forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE) node.textContent = ` ${values[index] || node.textContent.trim()}`;
      });
    });
  });
}

document.addEventListener("DOMContentLoaded", async () => {
  document.addEventListener("error", (event) => {
    if (event.target instanceof HTMLImageElement && event.target.matches("[data-product-image]")) {
      markImageMissing(event.target);
    }
  }, true);
  applyPageMode();
  window.addEventListener("hashchange", applyPageMode);
  bindEvents();
  applyLanguage();
  updateBudgetLabel();
  await loadProducts();
  await loadSession();
  await loadSelections();
  if (window.lucide) window.lucide.createIcons();
});

function bindEvents() {
  document.querySelector("#quizForm").addEventListener("submit", (event) => {
    event.preventDefault();
    submitRecommendation(false, buildQuizQuery());
  });
  document.querySelector("#followUpForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = document.querySelector("#followUpQuery");
    const query = input.value.trim();
    if (handleCommand(query)) return;
    submitRecommendation(hasProfileSignal(state.profile), query);
  });
  document.querySelector("#budget").addEventListener("change", updateBudgetLabel);
  document.querySelector("#resetSession").addEventListener("click", resetSession);
  document.querySelector("#compareSelected").addEventListener("click", renderCompareTable);
  document.querySelector("#compareClearAll").addEventListener("click", clearCompareSelections);
  document.querySelectorAll("[data-choice-group]").forEach((group) => {
    group.addEventListener("change", (event) => syncNoneChoice(group, event.target));
  });
  document.querySelectorAll("[data-lang]").forEach((button) => {
    button.addEventListener("click", () => setLanguage(button.dataset.lang));
  });
  document.querySelector("#offerModal")?.addEventListener("hidden.bs.modal", () => {
    state.activeOfferProductId = null;
  });
}

function buildQuizQuery() {
  const skinTypes = selectedValues("skinType");
  const productTypes = selectedValues("productType");
  const concerns = selectedValues("mainConcern");
  const textures = selectedValues("texture");
  const budget = document.querySelector("#budget").value;
  const allergy = document.querySelector("#allergyInput").value.trim();
  const parts = [];
  if (skinTypes.length) parts.push(`${skinTypes.join(", ")} 피부`);
  if (productTypes.length) parts.push(`${productTypes.join(", ")} 추천`);
  if (concerns.length) parts.push(`주요 고민은 ${concerns.join(", ")}`);
  if (textures.length) parts.push(`${textures.join(", ")} 제형 선호`);
  if (budget) parts.push(`${budget}원 이하`);
  if (allergy) parts.push(`${allergy} 성분은 피하고 싶어`);
  if (!parts.length) parts.push("기초 제품 추천");
  return parts.join(", ");
}

function selectedValues(name) {
  return [...document.querySelectorAll(`input[name="${name}"]:checked`)].map((input) => input.value).filter(Boolean);
}

function updateBudgetLabel() {
  const value = document.querySelector("#budget").value;
  document.querySelector("#budgetValue").textContent = value ? krw(Number(value)) : text("budgetNone");
}

function syncNoneChoice(group, target) {
  if (!target.matches("input[type='checkbox']")) return;
  const inputs = [...group.querySelectorAll("input[type='checkbox']")];
  const none = inputs.find((input) => input.dataset.none !== undefined);
  if (!none) return;
  if (target === none && none.checked) {
    inputs.filter((input) => input !== none).forEach((input) => {
      input.checked = false;
    });
  } else if (target !== none && target.checked) {
    none.checked = false;
  }
}

function apiUrl(path) {
  if (/^https?:\/\//i.test(path)) return path;
  return `${API_BASE_URL}${path}`;
}

function createAnonymousSessionToken() {
  const bytes = new Uint8Array(24);
  window.crypto.getRandomValues(bytes);
  const body = Array.from(bytes, (value) => value.toString(16).padStart(2, "0")).join("");
  return `kb_${body}`;
}

function validSessionIssuedAt(value) {
  const issuedAt = Number(value);
  const age = Date.now() - issuedAt;
  return Number.isFinite(issuedAt) && age >= 0 && age < SESSION_MAX_AGE_MS;
}

function getAnonymousSessionToken() {
  if (SESSION_PATTERN.test(memorySessionToken) && validSessionIssuedAt(memorySessionIssuedAt)) {
    return memorySessionToken;
  }

  let storedToken = "";
  let storedIssuedAt = 0;
  try {
    storedToken = window.localStorage.getItem(SESSION_STORAGE_KEY) || "";
    storedIssuedAt = Number(window.localStorage.getItem(SESSION_ISSUED_AT_KEY) || 0);
  } catch {
    // Web Storage가 막힌 환경에서는 현재 페이지의 메모리 세션을 사용합니다.
  }

  const reuseStored = SESSION_PATTERN.test(storedToken) && validSessionIssuedAt(storedIssuedAt);
  memorySessionToken = reuseStored ? storedToken : createAnonymousSessionToken();
  memorySessionIssuedAt = reuseStored ? storedIssuedAt : Date.now();
  try {
    window.localStorage.setItem(SESSION_STORAGE_KEY, memorySessionToken);
    window.localStorage.setItem(SESSION_ISSUED_AT_KEY, String(memorySessionIssuedAt));
  } catch {
    // 요청 헤더에는 메모리에 보관한 토큰을 계속 사용합니다.
  }
  return memorySessionToken;
}

function rotateAnonymousSessionToken() {
  memorySessionToken = "";
  memorySessionIssuedAt = 0;
  try {
    window.localStorage.removeItem(SESSION_STORAGE_KEY);
    window.localStorage.removeItem(SESSION_ISSUED_AT_KEY);
  } catch {
    // 저장소가 막혀 있어도 메모리 토큰은 제거되었습니다.
  }
  return getAnonymousSessionToken();
}

async function apiFetch(path, options = {}) {
  return fetch(apiUrl(path), {
    ...options,
    credentials: "omit",
    headers: {
      ...(options.headers || {}),
      "X-KBeauty-Session": getAnonymousSessionToken(),
    },
  });
}

async function apiJson(path, options = {}) {
  const response = await apiFetch(path, options);
  let data = {};
  try {
    data = await response.json();
  } catch {
    data = {};
  }
  if (!response.ok) {
    const error = new Error(data.detail || `${response.status} ${response.statusText}`);
    error.data = data;
    error.status = response.status;
    throw error;
  }
  return data;
}

function isRecord(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function firstTextValue(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

function numberValue(...values) {
  for (const value of values) {
    if (value === null || value === undefined || value === "") continue;
    const number = Number(value);
    if (Number.isFinite(number)) return number;
  }
  return null;
}

function dateTextValue(...values) {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
    if (typeof value === "number" && Number.isFinite(value)) {
      const milliseconds = value < 1_000_000_000_000 ? value * 1000 : value;
      return new Date(milliseconds).toISOString();
    }
  }
  return "";
}

function booleanValue(value) {
  if (typeof value === "boolean") return value;
  if (typeof value === "number") return value !== 0;
  if (typeof value === "string") {
    const normalized = value.trim().toLowerCase();
    if (["true", "1", "yes"].includes(normalized)) return true;
    if (["false", "0", "no"].includes(normalized)) return false;
  }
  return null;
}

function normalizeAvailability(...values) {
  const value = firstTextValue(...values).toLowerCase().replace(/[\s-]+/g, "_");
  if (["in_stock", "available", "on_sale", "판매중", "재고있음"].includes(value)) return "in_stock";
  if (["out_of_stock", "sold_out", "unavailable", "품절", "재고없음"].includes(value)) return "out_of_stock";
  if (["preorder", "pre_order", "예약판매"].includes(value)) return "preorder";
  return "unknown";
}

function backendRedirectUrl(value) {
  const raw = firstTextValue(value);
  if (!raw) return "";
  try {
    const apiOrigin = new URL(apiUrl("/"), window.location.href).origin;
    const parsed = new URL(raw, `${apiOrigin}/`);
    const localHttp = parsed.protocol === "http:" && ["localhost", "127.0.0.1"].includes(parsed.hostname);
    if ((!localHttp && parsed.protocol !== "https:") || parsed.origin !== apiOrigin || !parsed.pathname.startsWith("/r/")) return "";
    return parsed.toString();
  } catch {
    return "";
  }
}

function normalizeOffer(raw, index = 0) {
  if (!isRecord(raw)) return null;
  const retailer = isRecord(raw.retailer) ? raw.retailer : {};
  const priceData = isRecord(raw.price) ? raw.price : {};
  const listPriceData = isRecord(raw.list_price)
    ? raw.list_price
    : isRecord(raw.listPrice)
      ? raw.listPrice
      : {};
  const stock = isRecord(raw.stock) ? raw.stock : {};
  const freshness = isRecord(raw.freshness) ? raw.freshness : {};
  const affiliateDetails = isRecord(raw.affiliate) ? raw.affiliate : {};
  const retailerName = firstTextValue(
    raw.retailer_name,
    raw.retailerName,
    raw.merchant_name,
    raw.store_name,
    retailer.name,
  );
  if (!retailerName) return null;

  const explicitFresh = booleanValue(raw.is_fresh ?? raw.isFresh ?? raw.fresh ?? freshness.is_fresh);
  const explicitStale = booleanValue(raw.is_stale ?? raw.isStale ?? raw.stale ?? freshness.is_stale);
  const freshnessStatus = firstTextValue(
    typeof raw.freshness === "string" ? raw.freshness : "",
    raw.freshness_status,
    raw.freshnessStatus,
    freshness.status,
  ).toLowerCase();
  const freshnessState = explicitStale === true || explicitFresh === false || ["stale", "expired"].includes(freshnessStatus)
    ? "stale"
    : explicitFresh === true || explicitStale === false || ["fresh", "current"].includes(freshnessStatus)
      ? "fresh"
      : "unknown";
  const affiliate = booleanValue(
    raw.is_affiliate
      ?? raw.isAffiliate
      ?? (isRecord(raw.affiliate)
        ? affiliateDetails.active ?? affiliateDetails.enabled ?? affiliateDetails.is_affiliate
        : raw.affiliate),
  );
  const relationship = firstTextValue(raw.relationship, raw.link_type, raw.linkType).toLowerCase();
  const retailerId = firstTextValue(raw.retailer_id, raw.retailerId, retailer.id);
  const currency = firstTextValue(raw.currency, priceData.currency).toUpperCase() || "KRW";
  const priceAmount = numberValue(
    raw.price_krw,
    raw.priceKrw,
    raw.sale_price_krw,
    raw.salePriceKrw,
    raw.price_amount,
    raw.current_price,
    priceData.amount_krw,
    priceData.amount,
  );
  const listPriceAmount = numberValue(
    raw.list_price_krw,
    raw.listPriceKrw,
    raw.original_price_krw,
    raw.originalPriceKrw,
    listPriceData.amount_krw,
    listPriceData.amount,
    raw.list_price,
    priceData.list_amount_krw,
    priceData.list_amount,
  );

  return {
    id: firstTextValue(raw.id, raw.offer_id, raw.offerId) || `${retailerId || retailerName}-${index}`,
    retailerId,
    retailerName,
    currency,
    priceAmount,
    listPriceAmount,
    priceKrw: currency === "KRW" ? priceAmount : null,
    listPriceKrw: currency === "KRW" ? listPriceAmount : null,
    availability: normalizeAvailability(
      raw.availability,
      raw.availability_status,
      raw.availabilityStatus,
      raw.stock_status,
      raw.stockStatus,
      stock.status,
    ),
    freshness: freshnessState,
    checkedAt: dateTextValue(
      raw.checked_at,
      raw.checkedAt,
      raw.price_checked_at,
      raw.priceCheckedAt,
      raw.observed_at,
      raw.updated_at,
      freshness.checked_at,
    ),
    clickUrl: backendRedirectUrl(raw.redirect_url ?? raw.redirectUrl ?? raw.click_url ?? raw.clickUrl),
    isLinkOnly: booleanValue(raw.link_only ?? raw.linkOnly) || false,
    linkType: firstTextValue(raw.link_type, raw.linkType) === "retailer_search"
      ? "retailer_search"
      : "product_page",
    isAffiliate: affiliate ?? relationship === "affiliate",
    affiliateLabel: firstTextValue(
      raw.affiliate_label,
      raw.affiliateLabel,
      affiliateDetails.label,
    ),
    affiliateDisclosure: firstTextValue(
      raw.affiliate_disclosure,
      raw.affiliateDisclosure,
      raw.disclosure,
      affiliateDetails.disclosure,
    ),
  };
}

function normalizeCommerce(raw) {
  if (!isRecord(raw)) return null;
  const retailerCount = numberValue(raw.retailer_count, raw.retailerCount) || 0;
  const offerCount = numberValue(raw.offer_count, raw.offerCount) ?? retailerCount;
  const freshOfferCount = numberValue(raw.fresh_offer_count, raw.freshOfferCount) || 0;
  const lowestFreshPriceKrw = numberValue(
    raw.lowest_fresh_price_krw,
    raw.lowestFreshPriceKrw,
    raw.lowest_price_krw,
    raw.lowestPriceKrw,
  );
  const hasAffiliateOffers = booleanValue(raw.has_affiliate_offers ?? raw.hasAffiliateOffers ?? raw.has_affiliate) || false;
  if (!retailerCount && !offerCount && !freshOfferCount && lowestFreshPriceKrw === null) return null;
  return { retailerCount, offerCount, freshOfferCount, lowestFreshPriceKrw, hasAffiliateOffers };
}

function legacyOfferFromProduct(product) {
  const priceKrw = numberValue(product.price_krw, product.oliveyoung_price_krw);
  const retailerName = firstTextValue(product.retailer_name) || (product.oliveyoung_url ? "Olive Young" : "");
  const clickUrl = backendRedirectUrl(product.redirect_url ?? product.click_url);
  if (priceKrw === null && !retailerName && !clickUrl) return null;
  return {
    id: `legacy-${product.id}`,
    retailerId: "",
    retailerName: retailerName || (state.lang === "en" ? "Retailer" : "판매처"),
    priceKrw,
    listPriceKrw: null,
    priceAmount: priceKrw,
    listPriceAmount: null,
    currency: "KRW",
    availability: "unknown",
    freshness: "unknown",
    checkedAt: dateTextValue(product.price_checked_at, product.oliveyoung_verified_at),
    clickUrl,
    isAffiliate: false,
    affiliateDisclosure: "",
  };
}

function normalizeProduct(rawProduct, context = {}) {
  if (!isRecord(rawProduct)) return rawProduct;
  const product = { ...rawProduct };
  const commerce = normalizeCommerce(product.commerce ?? context.commerce ?? context.offer_summary);
  const offerCollections = [
    context.offers,
    context.retail_offers,
    product.offers,
    product.retail_offers,
    isRecord(product.offer_summary) ? product.offer_summary.offers : null,
  ];
  const rawOffers = offerCollections.find((value) => Array.isArray(value)) || [];
  const seen = new Set();
  const offers = rawOffers
    .map((offer, index) => normalizeOffer(offer, index))
    .filter((offer) => {
      if (!offer || seen.has(offer.id)) return false;
      seen.add(offer.id);
      return true;
    });
  const legacyOffer = offers.length ? null : legacyOfferFromProduct(product);
  product.offers = legacyOffer ? [legacyOffer] : offers;
  product.commerce = commerce || commerceFromOffers(product.offers);
  return product;
}

function commerceFromOffers(offers) {
  const active = (offers || []).filter((offer) => offer.availability !== "out_of_stock");
  const fresh = active.filter((offer) => offer.freshness === "fresh");
  const retailers = new Set(active.map((offer) => offer.retailerId || offer.retailerName).filter(Boolean));
  const freshPrices = fresh.map((offer) => offer.priceKrw).filter((value) => Number.isFinite(value));
  return {
    retailerCount: retailers.size,
    offerCount: active.length,
    freshOfferCount: fresh.length,
    lowestFreshPriceKrw: freshPrices.length ? Math.min(...freshPrices) : null,
    hasAffiliateOffers: active.some((offer) => offer.isAffiliate),
  };
}

function normalizeRecommendationItems(results) {
  return (Array.isArray(results) ? results : []).map((item) => {
    if (!isRecord(item) || !isRecord(item.product)) return item;
    return { ...item, product: normalizeProduct(item.product, item) };
  });
}

function emptySelections() {
  return { saved_ids: [], compare_ids: [], saved_products: [], compare_products: [], total_cost_krw: 0 };
}

function normalizeSelections(data) {
  const value = isRecord(data) ? data : {};
  return {
    ...emptySelections(),
    ...value,
    saved_products: (Array.isArray(value.saved_products) ? value.saved_products : []).map((product) => normalizeProduct(product)),
    compare_products: (Array.isArray(value.compare_products) ? value.compare_products : []).map((product) => normalizeProduct(product)),
  };
}

async function loadProducts() {
  try {
    const products = [];
    let cursor = 0;
    let endpoint = "/api/v2/products";
    do {
      let data;
      try {
        data = await apiJson(`${endpoint}?limit=100&cursor=${cursor}`);
      } catch (error) {
        if (cursor === 0 && endpoint === "/api/v2/products" && [404, 405].includes(error?.status)) {
          endpoint = "/api/products";
          continue;
        }
        throw error;
      }
      products.push(...(data.products || []));
      cursor = Number.isInteger(data.next_cursor) ? data.next_cursor : -1;
    } while (cursor >= 0 && products.length < 10_000);
    state.allProducts = products.map((product) => normalizeProduct(product));
    state.productsById.clear();
    state.allProducts.forEach((product) => state.productsById.set(product.id, product));
  } catch {
    state.allProducts = [];
    setStatus(text("backendConnectionFailed"));
  }
  renderCatalogs();
}

async function loadSession() {
  try {
    const data = await apiJson("/api/session");
    state.profile = data.profile || {};
  } catch {
    state.profile = {};
  }
  renderProfile(state.profile);
}

async function loadSelections() {
  try {
    state.selections = normalizeSelections(await apiJson("/api/selections"));
  } catch {
    state.selections = emptySelections();
  }
  await hydrateSelectedProducts();
  renderRoutine();
  renderCompareSummary();
  renderCompareTable();
  renderCatalogs();
}

async function submitRecommendation(isFollowUp, query) {
  if (!query) return;
  setStatus(isFollowUp ? text("followUpStatus") : text("submitStatus"));
  let data;
  try {
    const requestOptions = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        limit: 5,
        use_openai: false,
        language: state.lang,
        privacy_consent: Boolean(document.querySelector("#privacyConsent")?.checked),
        privacy_policy_version: "2026-07-22",
      }),
    };
    const path = isFollowUp ? "/api/v2/follow-up" : "/api/v2/recommend";
    try {
      data = await apiJson(path, requestOptions);
    } catch (error) {
      if ([404, 405].includes(error?.status)) {
        data = await apiJson(isFollowUp ? "/api/follow-up" : "/api/recommend", requestOptions);
      } else {
        throw error;
      }
    }
  } catch (error) {
    setStatus(error?.data?.detail || text("backendConnectionFailed"));
    return;
  }
  state.recommendationId = data.recommendation_id;
  state.profile = data.profile || {};
  state.currentResults = normalizeRecommendationItems(data.results);
  state.currentResults.forEach((item) => state.productsById.set(item.product.id, item.product));
  renderProfile(state.profile);
  renderResults(state.currentResults);
  document.querySelector("#followUpQuery").value = "";
  const countText = text(isFollowUp ? "followUpResultCount" : "resultCount").replace("{count}", String(state.currentResults.length));
  setStatus(countText);
  document.querySelector("#recommendation").scrollIntoView({ behavior: "smooth", block: "start" });
  if (window.lucide) window.lucide.createIcons();
}

function setStatus(message) {
  document.querySelector("#status").textContent = message;
}

function handleCommand(query) {
  const command = parseCommand(query);
  if (!command) return false;
  if (command === "resetCriteria") {
    resetCriteria();
    return true;
  }
  if (command === "addAllCompare") {
    addCurrentResultsToSelection("compare");
    return true;
  }
  if (command === "addAllRoutine") {
    addCurrentResultsToSelection("saved");
    return true;
  }
  return false;
}

function parseCommand(query) {
  const normalized = normalizeText(query);
  if (!normalized) return null;
  const wantsAll = includesAny(normalized, ["all", "every", "current", "recommended", "recommendations", "전체", "전부", "모두", "다", "추천", "추천제품", "추천 제품"]);
  const wantsCompare = includesAny(normalized, ["compare", "comparison", "비교", "비교페이지", "비교 페이지"]);
  const wantsRoutine = includesAny(normalized, ["routine", "cart", "save", "saved", "basket", "루틴", "장바구니", "저장", "담아", "넣어"]);
  const wantsReset = includesAny(normalized, ["reset", "clear", "remove", "delete", "리셋", "초기화", "비워", "지워", "삭제"]);
  const targetsCriteria = includesAny(normalized, ["criteria", "condition", "conditions", "filter", "filters", "profile", "search", "follow up", "followup", "조건", "검색", "필터", "프로필", "후속"]);

  if (wantsReset && (targetsCriteria || wantsAll)) return "resetCriteria";
  if (wantsAll && wantsCompare) return "addAllCompare";
  if (wantsAll && wantsRoutine) return "addAllRoutine";
  return null;
}

function includesAny(value, terms) {
  return terms.some((term) => value.includes(term));
}

async function resetCriteria() {
  try {
    await apiJson("/api/profile", { method: "DELETE" });
  } catch {
    setStatus(text("backendConnectionFailed"));
    return;
  }
  state.recommendationId = null;
  state.profile = {};
  document.querySelector("#followUpQuery").value = "";
  renderProfile({});
  setStatus(text("criteriaReset"));
}

async function addCurrentResultsToSelection(listType) {
  const products = state.currentResults.map((item) => item.product).filter(Boolean);
  if (!products.length) {
    setStatus(text("noCurrentResults"));
    return;
  }
  for (const product of products) {
    if (!(await setSelection(product.id, listType, true))) return;
  }
  await hydrateSelectedProducts();
  renderRoutine();
  renderCompareSummary();
  renderCatalogs();
  renderResults(state.currentResults);
  if (listType === "compare") renderCompareTable();
  document.querySelector("#followUpQuery").value = "";
  setStatus(text(listType === "compare" ? "allCompareAdded" : "allRoutineAdded").replace("{count}", String(products.length)));
  if (window.lucide) window.lucide.createIcons();
}

function renderProfile(profile) {
  const fields = [
    "skin_type",
    "concerns",
    "desired_categories",
    "preferred_ingredients",
    "texture_preference",
    "max_price_krw",
    "min_price_krw",
    "allergies",
  ];
  const html = fields
    .map((field) => {
      const raw = profile?.[field];
      const value = Array.isArray(raw) ? raw.map(displayValue).join(", ") : displayValue(raw, field);
      return value ? `<span><strong>${labels[state.lang]?.[field] || field}</strong>${escapeHtml(value)}</span>` : "";
    })
    .join("");
  const blocked = Array.isArray(profile?.avoid_ingredients) ? profile.avoid_ingredients.map(displayValue).join(", ") : "";
  const blockedHtml = blocked ? `<span class="blocked-ingredients"><strong>${text("blockedIngredients")}</strong>${escapeHtml(blocked)}</span>` : "";
  const profileHtml = `${html}${blockedHtml}`;
  document.querySelector("#profileView").innerHTML = profileHtml || `<span>${text("profileEmpty")}</span>`;
}

function hasProfileSignal(profile) {
  if (!profile) return false;
  const listFields = ["concerns", "desired_categories", "preferred_ingredients", "sensitivities", "allergies", "avoid_ingredients"];
  if (listFields.some((field) => Array.isArray(profile[field]) && profile[field].length > 0)) return true;
  return Boolean(
    profile.skin_type ||
      profile.texture_preference ||
      profile.location_or_climate ||
      profile.pregnant_or_nursing ||
      profile.max_price_usd != null ||
      profile.max_price_krw != null ||
      profile.min_price_usd != null ||
      profile.min_price_krw != null
  );
}

function displayValue(value, field = "") {
  if (!value) return "";
  if (field === "max_price_krw" || field === "min_price_krw") return krw(Number(value));
  if (typeof value === "number") return String(value);
  const normalized = String(value).toLowerCase();
  const label = valueLabels[state.lang]?.[normalized] || valueLabels[state.lang]?.[value] || valueLabels.ko[normalized] || valueLabels.ko[value];
  return label || String(value).replaceAll("_", " ");
}

function displayProductName(product) {
  return state.lang === "ko" ? product.display_name_ko || product.name : product.name;
}

function displayIngredient(ingredient) {
  return state.lang === "ko" ? displayValue(ingredient) : String(ingredient);
}

function displayIngredients(ingredients, limit = 8) {
  return (ingredients || []).slice(0, limit).map(displayIngredient).join(", ");
}

function normalizeText(value) {
  return String(value || "").toLowerCase().replace(/[^a-z0-9가-힣]+/g, " ").trim();
}

function orderedIngredientExplanations(product, matchedIngredients) {
  const explanations = product.ingredient_explanations || [];
  const priority = (matchedIngredients || []).map((item) => normalizeText(item));
  return [...explanations].sort((left, right) => {
    const leftIndex = priority.indexOf(normalizeText(left.name));
    const rightIndex = priority.indexOf(normalizeText(right.name));
    if (leftIndex !== -1 || rightIndex !== -1) {
      if (leftIndex === -1) return 1;
      if (rightIndex === -1) return -1;
      return leftIndex - rightIndex;
    }
    return 0;
  });
}

function renderResults(results) {
  const container = document.querySelector("#results");
  container.innerHTML = results.map(renderProductCard).join("");
  container.querySelectorAll("[data-select-product]").forEach((button) => {
    button.addEventListener("click", () => toggleSelection(button.dataset.productId, button.dataset.listType));
  });
  container.querySelectorAll("[data-ingredient]").forEach((button) => {
    button.addEventListener("click", () => showIngredient(button.dataset.productId, button.dataset.ingredient));
  });
  bindOfferButtons(container);
}

function renderProductCard(item) {
  const product = item.product;
  const isSaved = state.selections.saved_ids?.includes(product.id);
  const isCompare = state.selections.compare_ids?.includes(product.id);
  const reasons = item.display_reasons || item.reasons || [];
  const personalizedReason = item.personalized_reason || reasons.slice(0, 3).join(" ");
  const matchedRaw = item.matched_ingredients || [];
  const matched = item.display_matched_ingredients || matchedRaw;
  const ingredientButtons = orderedIngredientExplanations(product, matchedRaw)
    .slice(0, 6)
    .map(
      (ingredient) =>
        `<button type="button" class="ingredient-chip" data-product-id="${product.id}" data-ingredient="${escapeHtml(ingredient.name)}">${escapeHtml(displayIngredient(ingredient.label || ingredient.name))}</button>`
    )
    .join("");
  return `
    <article class="product-card">
      <div class="product-media ${product.image_url ? "" : "image-missing"}" data-image-frame>
        ${productImage(product)}
        ${imageSourceBadge(product)}
      </div>
      <div class="product-body">
        <div class="product-head">
          <div>
            <p class="brand">${escapeHtml(product.brand)}</p>
            <h3>${escapeHtml(displayProductName(product))}</h3>
          </div>
          ${productPriceSummaryHtml(product)}
        </div>
        <p class="meta">${escapeHtml(displayValue(product.category))} · ${skinCompatibility(product)}</p>
        <div class="note-list">
          <strong>${text("recommendedReason")}</strong>
          <p>${escapeHtml(personalizedReason || text("noReason"))}</p>
        </div>
        <div class="ingredient-row">
          <strong>${text("ingredients")}</strong>
          <div>${ingredientButtons || matched.map((item) => `<span class="chip">${escapeHtml(displayIngredient(item))}</span>`).join("")}</div>
        </div>
        <div class="review-box">
          <strong>${text("review")}</strong>
          <p>${escapeHtml(reviewSummary(product, "noReview"))}</p>
          ${reviewExcerpts(product)}
        </div>
        <div class="combo-box">
          <strong>${text("combo")}</strong>
          <span>${escapeHtml(recommendedCombo(product))}</span>
        </div>
        <div class="product-actions">
          <button class="secondary ${isSaved ? "selected" : ""}" type="button" data-select-product data-list-type="saved" data-product-id="${product.id}">
            <i data-lucide="${isSaved ? "bookmark-check" : "bookmark"}"></i><span>${isSaved ? text("saved") : text("save")}</span>
          </button>
          <button class="secondary ${isCompare ? "selected" : ""}" type="button" data-select-product data-list-type="compare" data-product-id="${product.id}">
            <i data-lucide="scale"></i><span>${text("compare")}</span>
          </button>
          ${offerComparisonButton(product)}
          ${sourceLinkButton(product)}
        </div>
      </div>
    </article>
  `;
}

async function toggleSelection(productId, listType) {
  const ids = state.selections[`${listType}_ids`] || [];
  const selected = !ids.includes(productId);
  if (!(await setSelection(productId, listType, selected))) return;
  await hydrateSelectedProducts();
  renderRoutine();
  renderCompareSummary();
  renderCatalogs();
  if (listType === "compare" || !document.querySelector("#compareTable").classList.contains("hidden")) renderCompareTable();
  const cards = [...document.querySelectorAll("[data-select-product]")];
  cards.forEach((button) => {
      if (button.dataset.productId === productId && button.dataset.listType === listType) {
        button.classList.toggle("selected", selected);
        const span = button.querySelector("span");
        if (span && listType === "saved") span.textContent = selected ? text("saved") : text("save");
      }
  });
  if (window.lucide) window.lucide.createIcons();
}

async function setSelection(productId, listType, selected) {
  try {
    state.selections = normalizeSelections(await apiJson("/api/selections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ product_id: productId, list_type: listType, selected }),
    }));
    return true;
  } catch {
    setStatus(text("backendConnectionFailed"));
    return false;
  }
}

async function hydrateSelectedProducts() {
  for (const key of ["saved_products", "compare_products"]) {
    state.selections[key] = (state.selections[key] || []).map((legacyProduct) => {
      const catalogProduct = state.productsById.get(legacyProduct.id);
      const product = catalogProduct
        ? normalizeProduct({ ...legacyProduct, ...catalogProduct })
        : legacyProduct;
      state.productsById.set(product.id, product);
      return product;
    });
  }
}

function renderCompareSummary() {
  const count = state.selections.compare_products?.length || 0;
  const empty = document.querySelector("#compareEmpty");
  const clearAll = document.querySelector("#compareClearAll");
  empty.textContent = text("compareEmpty");
  empty.classList.toggle("hidden", count > 0);
  clearAll?.classList.toggle("hidden", count === 0);
  if (!count) document.querySelector("#compareTable").classList.add("hidden");
}

function renderCompareTable() {
  const products = state.selections.compare_products || [];
  const wrap = document.querySelector("#compareTable");
  if (!products.length) {
    renderCompareSummary();
    return;
  }
  wrap.classList.remove("hidden");
  wrap.innerHTML = `
    <table class="compare-table">
      <thead>
        <tr>
          <th>${text("compareStandard")}</th>
          ${products.map((product) => `<th>${escapeHtml(displayProductName(product))}<button class="table-remove" type="button" data-remove-selection data-list-type="compare" data-product-id="${product.id}">${text("remove")}</button></th>`).join("")}
        </tr>
      </thead>
      <tbody>
        <tr><th>${text("image")}</th>${products.map((product) => `<td><div class="compare-thumb ${product.image_url ? "" : "image-missing"}" data-image-frame>${productImage(product)}${imageSourceBadge(product)}</div></td>`).join("")}</tr>
        <tr><th>${text("cost")}</th>${products.map((product) => `<td>${productPriceSummaryHtml(product, true)}${offerComparisonButton(product, true)}</td>`).join("")}</tr>
        <tr><th>${text("skinCompatibility")}</th>${products.map((product) => `<td>${skinCompatibility(product)}</td>`).join("")}</tr>
        <tr><th>${text("ingredient")}</th>${products.map((product) => `<td>${escapeHtml(displayIngredients(product.ingredients, 8))}</td>`).join("")}</tr>
        <tr><th>${text("review")}</th>${products.map((product) => `<td>${escapeHtml(reviewSummary(product, "noReviewShort"))}${reviewExcerpts(product, { compact: true })}</td>`).join("")}</tr>
      </tbody>
    </table>
  `;
  wrap.querySelectorAll("[data-remove-selection]").forEach((button) => {
    button.addEventListener("click", () => removeSelection(button.dataset.productId, button.dataset.listType));
  });
  bindOfferButtons(wrap);
}

async function clearCompareSelections() {
  const ids = [...(state.selections.compare_ids || [])];
  for (const productId of ids) {
    if (!(await setSelection(productId, "compare", false))) return;
  }
  await hydrateSelectedProducts();
  document.querySelector("#compareTable").innerHTML = "";
  document.querySelector("#compareTable").classList.add("hidden");
  renderCompareSummary();
  renderCatalogs();
  if (window.lucide) window.lucide.createIcons();
}

function renderRoutine() {
  const products = state.selections.saved_products || [];
  syncRoutineSelectedProducts(products);
  const total = products.reduce((sum, product) => sum + productKrwValue(product), 0);
  const selectedTotal = products
    .filter((product) => state.routineSelectedIds.has(product.id))
    .reduce((sum, product) => sum + productKrwValue(product), 0);
  const productsWithFreshPrice = products.filter((product) => productKrwValue(product) > 0).length;
  const selectedProducts = products.filter((product) => state.routineSelectedIds.has(product.id));
  const selectedWithFreshPrice = selectedProducts.filter((product) => productKrwValue(product) > 0).length;
  updateRoutineSelectAll(products);
  document.querySelector("#routineTotal").textContent = products.length && !productsWithFreshPrice ? text("needPrice") : krw(total);
  document.querySelector("#routineSelectedTotal").textContent = selectedProducts.length && !selectedWithFreshPrice ? text("needPrice") : krw(selectedTotal);
  const empty = document.querySelector("#routineEmpty");
  empty.textContent = text("routineEmpty");
  empty.classList.toggle("hidden", products.length > 0);
  document.querySelector("#routineTotals")?.classList.toggle("hidden", products.length === 0);
  document.querySelector("#routineList").innerHTML = products
    .map(
      (product) => `
      <article class="routine-item">
        <label class="routine-check" aria-label="${escapeHtml(displayProductName(product))}">
          <input type="checkbox" data-routine-select data-product-id="${product.id}" ${state.routineSelectedIds.has(product.id) ? "checked" : ""} />
        </label>
        <div class="routine-thumb ${product.image_url ? "" : "image-missing"}" data-image-frame>
          ${productImage(product)}
        </div>
        <div class="routine-info">
          <span class="step">${escapeHtml(displayValue(product.category))}</span>
          <h3>${escapeHtml(displayProductName(product))}</h3>
          <p>${product.source_updated_at || product.oliveyoung_verified_at ? `${text("verifiedDate")} ${formatVerifiedAt(product.source_updated_at || product.oliveyoung_verified_at)}` : ""}</p>
        </div>
        <div class="routine-price">
          <span>${text("cost")}</span>
          <strong>${price(product)}</strong>
        </div>
        <div class="routine-actions">
          <button class="secondary" type="button" data-remove-selection data-list-type="saved" data-product-id="${product.id}">${text("remove")}</button>
          ${offerComparisonButton(product)}
          ${sourceLinkButton(product)}
        </div>
      </article>`
    )
    .join("");
  document.querySelector("#routineList").querySelectorAll("[data-routine-select]").forEach((input) => {
    input.addEventListener("change", () => {
      if (input.checked) state.routineSelectedIds.add(input.dataset.productId);
      else state.routineSelectedIds.delete(input.dataset.productId);
      renderRoutine();
    });
  });
  document.querySelector("#routineList").querySelectorAll("[data-remove-selection]").forEach((button) => {
    button.addEventListener("click", () => removeSelection(button.dataset.productId, button.dataset.listType));
  });
  bindOfferButtons(document.querySelector("#routineList"));
}

function updateRoutineSelectAll(products) {
  const button = document.querySelector("#routineSelectAll");
  if (!button) return;
  const hasProducts = products.length > 0;
  const allSelected = hasProducts && products.every((product) => state.routineSelectedIds.has(product.id));
  button.classList.toggle("hidden", !hasProducts);
  button.dataset.selectAllMode = allSelected ? "deselect" : "select";
  const label = button.querySelector("span") || button;
  label.textContent = allSelected ? text("deselectAll") : text("selectAll");
  button.onclick = () => {
    if (button.dataset.selectAllMode === "deselect") {
      products.forEach((product) => state.routineSelectedIds.delete(product.id));
    } else {
      products.forEach((product) => {
        state.routineSelectedIds.add(product.id);
        state.routineKnownSavedIds.add(product.id);
      });
    }
    renderRoutine();
  };
}

function syncRoutineSelectedProducts(products) {
  const savedIds = new Set(products.map((product) => product.id));
  state.routineSelectedIds = new Set([...state.routineSelectedIds].filter((id) => savedIds.has(id)));
  state.routineKnownSavedIds = new Set([...state.routineKnownSavedIds].filter((id) => savedIds.has(id)));
  for (const product of products) {
    if (!state.routineKnownSavedIds.has(product.id)) {
      state.routineSelectedIds.add(product.id);
      state.routineKnownSavedIds.add(product.id);
    }
  }
}

function productKrwValue(product) {
  return Number(product?.commerce?.lowestFreshPriceKrw || 0);
}

function showIngredient(productId, ingredientName) {
  const product = state.productsById.get(productId);
  const ingredient = product?.ingredient_explanations?.find((item) => item.name === ingredientName);
  if (!ingredient) return;
  document.querySelector("#ingredientModalTitle").textContent = state.lang === "ko" ? ingredient.display_name_ko || displayValue(ingredient.name) : ingredient.name;
  document.querySelector("#ingredientModalBody").innerHTML = `
    <p>${escapeHtml(state.lang === "ko" ? ingredient.display_rationale_ko || ingredient.rationale : ingredient.rationale)}</p>
    <dl class="ingredient-detail">
      <div><dt>${text("evidenceLevel")}</dt><dd>${escapeHtml(evidenceLabel(ingredient.evidence_level))}</dd></div>
      <div><dt>${text("supportConcerns")}</dt><dd>${escapeHtml(ingredientList(ingredient, "supports") || "-")}</dd></div>
      <div><dt>${text("suitableSkin")}</dt><dd>${escapeHtml(ingredientList(ingredient, "suitable_for") || "-")}</dd></div>
      <div><dt>${text("caution")}</dt><dd>${escapeHtml(ingredientList(ingredient, "cautions") || text("noSpecialCaution"))}</dd></div>
    </dl>
  `;
  bootstrap.Modal.getOrCreateInstance(document.querySelector("#ingredientModal")).show();
}

async function resetSession() {
  try {
    await apiJson("/api/session", { method: "DELETE" });
  } catch {
    setStatus(text("backendConnectionFailed"));
    return;
  }
  rotateAnonymousSessionToken();
  state.recommendationId = null;
  state.profile = {};
  state.currentResults = [];
  state.activeOfferProductId = null;
  state.offerRequests.clear();
  state.selections = { saved_ids: [], compare_ids: [], saved_products: [], compare_products: [], total_cost_krw: 0 };
  state.routineSelectedIds.clear();
  state.routineKnownSavedIds.clear();
  document.querySelector("#results").innerHTML = "";
  document.querySelector("#compareTable").innerHTML = "";
  document.querySelector("#compareTable").classList.add("hidden");
  const privacyConsent = document.querySelector("#privacyConsent");
  if (privacyConsent) privacyConsent.checked = false;
  bootstrap.Modal.getInstance(document.querySelector("#offerModal"))?.hide();
  setStatus(text("reset"));
  renderProfile({});
  renderRoutine();
  renderCompareSummary();
}

function renderCatalogs() {
  renderSelectionCatalog("compareCatalog", "compare");
  renderSelectionCatalog("routineCatalog", "saved");
}

function renderSelectionCatalog(containerId, listType) {
  const container = document.querySelector(`#${containerId}`);
  if (!container) return;
  const selectedIds = state.selections[`${listType}_ids`] || [];
  const showImageBadge = containerId !== "routineCatalog";
  container.innerHTML = state.allProducts
    .map((product) => {
      const selected = selectedIds.includes(product.id);
      return `
        <article class="catalog-item">
          <div class="catalog-thumb ${product.image_url ? "" : "image-missing"}" data-image-frame>
            ${productImage(product)}
            ${showImageBadge ? imageSourceBadge(product) : ""}
          </div>
          <div>
            <span>${escapeHtml(product.brand)} · ${escapeHtml(displayValue(product.category))}</span>
            <h3>${escapeHtml(displayProductName(product))}</h3>
            <div class="catalog-price">${productPriceSummaryHtml(product, true)}</div>
          </div>
          ${offerComparisonButton(product, true)}
          <button class="secondary ${selected ? "selected" : ""}" type="button" data-select-product data-list-type="${listType}" data-product-id="${product.id}">
            ${selected ? text("selected") : listType === "compare" ? text("compareAdd") : text("routineAdd")}
          </button>
        </article>`;
    })
    .join("");
  container.querySelectorAll("[data-select-product]").forEach((button) => {
    button.addEventListener("click", () => toggleSelection(button.dataset.productId, button.dataset.listType));
  });
  bindOfferButtons(container);
}

async function removeSelection(productId, listType) {
  if (!(await setSelection(productId, listType, false))) return;
  renderRoutine();
  renderCompareSummary();
  renderCompareTable();
  renderCatalogs();
  if (window.lucide) window.lucide.createIcons();
}

function applyPageMode() {
  const path = `${window.location.pathname}${window.location.hash}`;
  document.body.dataset.page = path.includes("compare") ? "compare" : path.includes("routine") ? "routine" : "home";
}

function skinCompatibility(product) {
  return (product.suited_skin_types || []).map(displayValue).join(", ") || text("noSkinFit");
}

function recommendedCombo(product) {
  const combos = {
    ko: {
      cleanser: "토너 또는 수분 세럼과 함께 사용",
      toner: "세럼 전 단계에서 가볍게 레이어링",
      serum: "보습제와 함께 장벽 루틴으로 마무리",
      eye_care: "눈가에 소량 사용하고 자극 여부 확인",
      face_mask: "주 1~2회 피부 반응을 보며 사용",
      lip_care: "건조할 때 얇게 덧바르기",
      exfoliator: "과도한 사용을 피하고 보습과 선케어 병행",
      body_cleanser: "샤워 단계에서 사용하고 바디 보습으로 마무리",
      body_moisturizer: "샤워 후 물기가 마르기 전에 고르게 바르기",
      body_exfoliator: "주 1~2회 피부 반응을 보며 사용",
      shampoo: "두피와 모발을 씻은 뒤 충분히 헹구기",
      conditioner: "샴푸 후 모발 중간부터 끝부분에 사용",
      hair_treatment: "제품 사용법에 따라 모발 또는 두피에 적용",
      base_makeup: "기초와 선케어 다음 단계에서 얇게 바르기",
      eye_makeup: "눈가 자극이 생기면 즉시 사용을 중단",
      lip_makeup: "입술 상태를 확인하며 위생적으로 사용",
      moisturizer: "세럼 후 수분 잠금 단계",
      sunscreen: "아침 루틴 마지막 단계",
      default: "기초 루틴 안에서 피부 반응을 보며 조합",
    },
    en: {
      cleanser: "Pair with a toner or hydrating serum",
      toner: "Layer lightly before serum",
      serum: "Finish with a moisturizer for barrier support",
      eye_care: "Use a small amount around the eye area and monitor for irritation",
      face_mask: "Use once or twice weekly while monitoring skin response",
      lip_care: "Apply a thin layer whenever lips feel dry",
      exfoliator: "Avoid overuse and pair with moisturizer and sunscreen",
      body_cleanser: "Use in the shower and follow with a body moisturizer",
      body_moisturizer: "Apply evenly after showering while skin is slightly damp",
      body_exfoliator: "Use once or twice weekly while monitoring skin response",
      shampoo: "Cleanse the scalp and hair, then rinse thoroughly",
      conditioner: "Apply from mid-lengths to ends after shampooing",
      hair_treatment: "Follow the product directions for hair or scalp use",
      base_makeup: "Apply a thin layer after skincare and sunscreen",
      eye_makeup: "Stop use promptly if eye-area irritation occurs",
      lip_makeup: "Use hygienically while monitoring lip condition",
      moisturizer: "Use after serum to seal in hydration",
      sunscreen: "Use as the final step in the morning routine",
      default: "Combine within a basic routine while watching skin response",
    },
  };
  const localized = combos[state.lang] || combos.ko;
  return localized[product.category] || localized.default;
}

function reviewSummary(product, emptyKey) {
  const summary = state.lang === "en" ? product.review_summary_en : product.review_summary;
  return cleanReviewSummary(summary) || text(emptyKey);
}

function reviewExcerpts(product, options = {}) {
  const positive = localizedReviewList(product, "positive").slice(0, options.compact ? 1 : 2);
  const negative = localizedReviewList(product, "negative").slice(0, options.compact ? 1 : 2);
  if (!positive.length && !negative.length) return "";
  const sections = [
    reviewExcerptGroup(text("positiveReview"), positive, "positive"),
    reviewExcerptGroup(text("negativeReview"), negative, "negative"),
  ].filter(Boolean).join("");
  const source = product.review_source_url || product.source_url || "";
  const sourceLink = source
    ? `<a href="${escapeHtml(source)}" target="_blank" rel="noreferrer">${text("reviewSource")}</a>`
    : "";
  return `<div class="actual-review-box ${options.compact ? "compact" : ""}"><span>${text("actualReviews")}</span>${sections}${sourceLink}</div>`;
}

function localizedReviewList(product, sentiment) {
  const koKey = sentiment === "positive" ? "positive_reviews" : "negative_reviews";
  const enKey = sentiment === "positive" ? "positive_reviews_en" : "negative_reviews_en";
  const preferred = state.lang === "en" ? product[enKey] : product[koKey];
  const fallback = state.lang === "en" ? product[koKey] : product[enKey];
  return Array.isArray(preferred) && preferred.length ? preferred : Array.isArray(fallback) ? fallback : [];
}

function reviewExcerptGroup(label, reviews, sentiment) {
  if (!reviews.length) return "";
  return `
    <div class="actual-review-group ${sentiment}">
      <em>${label}</em>
      ${reviews.map((review) => `<q>${escapeHtml(review)}</q>`).join("")}
    </div>
  `;
}

function cleanReviewSummary(summary) {
  return String(summary || "")
    .replace(/^큐레이션 리뷰 신호:\s*/i, "")
    .replace(/^Curated review signal:\s*/i, "")
    .trim();
}

function price(product) {
  const lowestFresh = numberValue(product?.commerce?.lowestFreshPriceKrw);
  if (lowestFresh !== null) return text("lowestPrice").replace("{price}", krw(lowestFresh));
  const visibleOffer = sortedOffers(product).find((offer) => offer.priceKrw !== null && offer.availability !== "out_of_stock");
  if (visibleOffer) return text("legacyPrice").replace("{price}", krw(visibleOffer.priceKrw));
  if (product?.price_usd) return `$${Number(product.price_usd).toFixed(2)}`;
  return text("needPrice");
}

function productPriceSummaryHtml(product, compact = false) {
  const commerce = product?.commerce || commerceFromOffers(product?.offers || []);
  const visibleOffer = sortedOffers(product).find((offer) => offer.priceKrw !== null && offer.availability !== "out_of_stock");
  const retailerCount = Number(commerce?.retailerCount || 0);
  const lowestFresh = numberValue(commerce?.lowestFreshPriceKrw);
  const details = [];
  if (lowestFresh !== null && commerce?.freshOfferCount) {
    details.push(text("freshRetailerCount").replace("{count}", String(commerce.freshOfferCount)));
  } else if (retailerCount) {
    details.push(text("retailerCount").replace("{count}", String(retailerCount)));
  }
  if (lowestFresh === null && visibleOffer) details.push(freshnessLabel(visibleOffer.freshness));
  return `
    <div class="price-stack ${compact ? "compact" : ""}">
      <strong class="price">${escapeHtml(price(product))}</strong>
      ${details.length ? `<span>${escapeHtml(details.join(" · "))}</span>` : ""}
      ${commerce?.hasAffiliateOffers ? `<span class="affiliate-mini-badge">${text("affiliateBadge")}</span>` : ""}
    </div>
  `;
}

function sortedOffers(product) {
  const freshnessRank = { fresh: 0, unknown: 1, stale: 2 };
  const availabilityRank = { in_stock: 0, unknown: 1, out_of_stock: 2 };
  return [...(product?.offers || [])].sort((left, right) => {
    const availabilityDifference = (availabilityRank[left.availability] ?? 1) - (availabilityRank[right.availability] ?? 1);
    if (availabilityDifference) return availabilityDifference;
    const freshnessDifference = (freshnessRank[left.freshness] ?? 1) - (freshnessRank[right.freshness] ?? 1);
    if (freshnessDifference) return freshnessDifference;
    const currencyDifference = (left.currency === "KRW" ? 0 : 1) - (right.currency === "KRW" ? 0 : 1);
    if (currencyDifference) return currencyDifference;
    const sameCurrency = left.currency === right.currency;
    const leftPrice = sameCurrency ? left.priceAmount ?? Number.POSITIVE_INFINITY : Number.POSITIVE_INFINITY;
    const rightPrice = sameCurrency ? right.priceAmount ?? Number.POSITIVE_INFINITY : Number.POSITIVE_INFINITY;
    return leftPrice - rightPrice || left.retailerName.localeCompare(right.retailerName);
  });
}

function offerComparisonButton(product, compact = false) {
  const commerce = product?.commerce || {};
  const hasOffers = Number(commerce.offerCount || commerce.retailerCount || 0) > 0 || Boolean(product?.offers?.length);
  if (!hasOffers) return "";
  const legacyOnly = product.offers?.length === 1 && String(product.offers[0].id).startsWith("legacy-");
  return `
    <button class="secondary offer-compare-button ${compact ? "compact" : ""}" type="button" data-compare-offers data-product-id="${escapeHtml(product.id)}">
      <i data-lucide="store"></i><span>${legacyOnly ? text("goToRetailer") : text("compareRetailers")}</span>
    </button>
  `;
}

function bindOfferButtons(container) {
  if (!container) return;
  container.querySelectorAll("[data-compare-offers]").forEach((button) => {
    button.addEventListener("click", () => showOfferComparison(button.dataset.productId));
  });
}

async function showOfferComparison(productId) {
  const initialProduct = state.productsById.get(productId);
  if (!initialProduct) return;
  state.activeOfferProductId = productId;
  renderOfferModal(initialProduct, text("offerLoading"));
  bootstrap.Modal.getOrCreateInstance(document.querySelector("#offerModal")).show();

  let request = state.offerRequests.get(productId);
  if (!request) {
    request = apiJson(`/api/v2/products/${encodeURIComponent(productId)}/offers`);
    state.offerRequests.set(productId, request);
  }
  try {
    const data = await request;
    const updatedProduct = productWithOfferResponse(state.productsById.get(productId) || initialProduct, data);
    replaceProductInState(updatedProduct);
    rerenderProductViews();
    if (state.activeOfferProductId === productId) renderOfferModal(updatedProduct);
  } catch {
    if (state.activeOfferProductId === productId) {
      const fallbackProduct = state.productsById.get(productId) || initialProduct;
      renderOfferModal(fallbackProduct, fallbackProduct.offers?.length ? "" : text("offerLoadFailed"));
    }
  } finally {
    state.offerRequests.delete(productId);
  }
}

function productWithOfferResponse(product, data) {
  const payload = isRecord(data) ? data : {};
  const nested = isRecord(payload.product) ? payload.product : {};
  const dataBlock = isRecord(payload.data) ? payload.data : {};
  const offers = [payload.offers, payload.retail_offers, nested.offers, dataBlock.offers, payload.items]
    .find((value) => Array.isArray(value)) || [];
  const commerce = payload.commerce || payload.offer_summary || payload.summary || nested.commerce || dataBlock.commerce || product.commerce;
  return normalizeProduct({ ...product, ...nested, offers, commerce }, { offers, commerce });
}

function replaceProductInState(product) {
  state.productsById.set(product.id, product);
  state.allProducts = state.allProducts.map((item) => item.id === product.id ? product : item);
  state.currentResults = state.currentResults.map((item) => item.product?.id === product.id ? { ...item, product } : item);
  for (const key of ["saved_products", "compare_products"]) {
    state.selections[key] = (state.selections[key] || []).map((item) => item.id === product.id ? product : item);
  }
}

function rerenderProductViews() {
  renderResults(state.currentResults);
  renderRoutine();
  renderCompareSummary();
  if (state.selections.compare_products?.length) renderCompareTable();
  renderCatalogs();
  if (window.lucide) window.lucide.createIcons();
}

function renderOfferModal(product, statusMessage = "") {
  if (!product) return;
  const offers = sortedOffers(product);
  setText("#offerModalEyebrow", text("compareRetailers"));
  setText("#offerModalTitle", displayProductName(product));
  setText("#offerModalSubtitle", text("offerModalTitle"));
  setText("#offerModalStatus", statusMessage);
  const list = document.querySelector("#offerModalList");
  list.innerHTML = offers.length ? offers.map(renderOfferRow).join("") : `<div class="offer-empty">${text("offerEmpty")}</div>`;

  const affiliateOffers = offers.filter((offer) => offer.isAffiliate);
  const disclosure = document.querySelector("#offerModalDisclosure");
  if (affiliateOffers.length) {
    const sourceDisclosures = [...new Set(affiliateOffers.map((offer) => offer.affiliateDisclosure).filter(Boolean))];
    disclosure.innerHTML = `<strong>${text("affiliateTitle")}</strong><p>${escapeHtml(sourceDisclosures[0] || text("affiliateDisclosure"))}</p>`;
    disclosure.classList.remove("hidden");
  } else {
    disclosure.innerHTML = "";
    disclosure.classList.add("hidden");
  }
  if (window.lucide) window.lucide.createIcons();
}

function renderOfferRow(offer) {
  const isRetailerSearch = offer.linkType === "retailer_search";
  const isEnglishRetailerSearch = isRetailerSearch && offer.retailerName.trim().toLowerCase() === "yesstyle";
  const priceText = isRetailerSearch
    ? text("retailerSearchPrice")
    : offer.priceAmount !== null
      ? money(offer.priceAmount, offer.currency)
      : text("needPrice");
  const showListPrice = offer.listPriceAmount !== null && offer.priceAmount !== null && offer.listPriceAmount > offer.priceAmount;
  const outboundLabel = isRetailerSearch
    ? text(isEnglishRetailerSearch ? "searchAtRetailerEnglish" : "searchAtRetailer").replace("{retailer}", offer.retailerName)
    : text("goToRetailer");
  const clickControl = offer.clickUrl
    ? `<a class="primary offer-outbound" href="${escapeHtml(offer.clickUrl)}" target="_blank" rel="nofollow sponsored noreferrer">${escapeHtml(outboundLabel)}<i data-lucide="external-link"></i></a>`
    : `<span class="offer-outbound disabled" aria-disabled="true">${text("noTrackedLink")}</span>`;
  return `
    <article class="offer-row ${offer.freshness === "stale" ? "is-stale" : ""}">
      <div class="offer-retailer">
        <div>
          <h3>${escapeHtml(offer.retailerName)}</h3>
          ${offer.isAffiliate ? `<span class="affiliate-badge">${escapeHtml(offer.affiliateLabel || text("affiliateBadge"))}</span>` : ""}
        </div>
        <div class="offer-badges">
          ${isRetailerSearch
            ? `<span class="availability-badge unknown">${text(isEnglishRetailerSearch ? "retailerSearchBadgeEnglish" : "retailerSearchBadge")}</span>`
            : `<span class="availability-badge ${offer.availability}">${availabilityLabel(offer.availability)}</span>
               <span class="freshness-badge ${offer.freshness}">${freshnessLabel(offer.freshness)}</span>`}
        </div>
      </div>
      <div class="offer-price-block">
        <strong>${priceText}</strong>
        ${showListPrice ? `<span>${text("listPrice").replace("{price}", money(offer.listPriceAmount, offer.currency))}</span>` : ""}
        <small>${escapeHtml(isRetailerSearch
          ? text(isEnglishRetailerSearch ? "retailerSearchNoteEnglish" : "retailerSearchNote")
          : offer.checkedAt
            ? text("checkedAt").replace("{date}", formatOfferCheckedAt(offer.checkedAt))
            : text("unknownFreshness"))}</small>
      </div>
      ${clickControl}
    </article>
  `;
}

function availabilityLabel(value) {
  if (value === "in_stock") return text("stockIn");
  if (value === "out_of_stock") return text("stockOut");
  if (value === "preorder") return text("stockPreorder");
  return text("stockUnknown");
}

function freshnessLabel(value) {
  return value === "fresh" ? text("freshPrice") : value === "stale" ? text("stalePrice") : text("unknownFreshness");
}

function formatOfferCheckedAt(value) {
  const raw = String(value || "");
  const timestamp = Date.parse(raw);
  if (Number.isFinite(timestamp)) {
    return new Intl.DateTimeFormat(state.lang === "en" ? "en-GB" : "ko-KR", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date(timestamp));
  }
  const date = raw.match(/\d{4}-\d{2}-\d{2}/)?.[0];
  return date || raw;
}

function sourceLinkButton(product) {
  if (product.catalog_source !== "open_beauty_facts" || !product.source_url) return "";
  return `<a class="link-button" href="${escapeHtml(product.source_url)}" target="_blank" rel="noreferrer">${text("productSource")}</a>`;
}

function koreanSourceUrl(...urls) {
  return urls.find((url) => isKoreanUrl(url)) || "#";
}

function englishUrl(...urls) {
  return urls.find((url) => url && !isKoreanUrl(url)) || "#";
}

function isKoreanUrl(url) {
  if (!url) return false;
  const normalized = String(url).toLowerCase();
  if (
    normalized.includes(".kr/") ||
    normalized.includes(".co.kr") ||
    normalized.includes("oliveyoung.co.kr") ||
    normalized.includes("glowpick.co.kr") ||
    normalized.includes("/kr/") ||
    normalized.includes("/ko/")
  ) {
    return true;
  }
  return false;
}


function productImage(product) {
  if (!product.image_url) return "";
  return `<img src="${escapeHtml(product.image_url)}" alt="${escapeHtml(displayProductName(product))}" loading="lazy" data-product-image />`;
}

function markImageMissing(image) {
  const frame = image.closest("[data-image-frame]");
  if (frame) frame.classList.add("image-missing");
  image.remove();
}

function imageSourceBadge(product) {
  const labels = {
    official: text("officialImage"),
    hwahae: text("hwahaeImage"),
    glowpick: text("glowpickImage"),
    open_beauty_facts: text("openBeautyFactsImage"),
    oliveyoung_snapshot: text("oliveyoungSnapshotImage"),
    retailer: text("retailerImage"),
  };
  const attributedOpenImage = product.image_source_type === "open_beauty_facts" && product.image_confidence === "reported";
  const label = product.image_confidence === "verified" || attributedOpenImage ? labels[product.image_source_type] : "";
  if (!label) return "";
  const source =
    state.lang === "ko"
      ? koreanSourceUrl(product.image_verified_source, product.official_url, product.source_url, product.oliveyoung_url)
      : englishUrl(product.image_verified_source, product.official_url, product.source_url);
  if (source === "#") return "";
  return `<a class="image-source-badge" href="${escapeHtml(source)}" target="_blank" rel="noreferrer">${label}</a>`;
}

function formatVerifiedAt(value) {
  const text = String(value || "");
  return text.includes(" ") ? text : `${text} 00:00 KST`;
}

function evidenceLabel(value) {
  if (state.lang === "en") return value;
  return { high: "높음", moderate: "중간", low: "낮음", insufficient: "부족" }[value] || value;
}

function ingredientList(ingredient, key) {
  if (state.lang === "ko") {
    const koreanKey = {
      supports: "display_supports_ko",
      suitable_for: "display_suitable_for_ko",
      cautions: "display_cautions_ko",
    }[key];
    return (ingredient[koreanKey] || []).join(key === "cautions" ? " " : ", ");
  }
  return (ingredient[key] || []).join(key === "cautions" ? " " : ", ");
}

function krw(value) {
  return `₩${Number(value || 0).toLocaleString("ko-KR")}`;
}

function money(value, currency = "KRW") {
  try {
    return new Intl.NumberFormat(state.lang === "en" ? "en-GB" : "ko-KR", {
      style: "currency",
      currency,
      maximumFractionDigits: currency === "KRW" ? 0 : 2,
    }).format(Number(value));
  } catch {
    return `${currency} ${Number(value).toLocaleString()}`;
  }
}

function renderBullets(items) {
  if (!items?.length) return `<p>${text("noReason")}</p>`;
  return `<ul>${items.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}
