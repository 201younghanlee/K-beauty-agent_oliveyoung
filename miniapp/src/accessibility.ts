export type AppScreen = 'survey' | 'results' | 'compare' | 'saved';

export function routeAnnouncement(screen: AppScreen, loading: boolean, itemCount: number): string {
  if (loading) {
    return '추천 제품을 분석하고 있어요.';
  }
  const labels: Record<AppScreen, string> = {
    survey: '맞춤 추천 설문 화면으로 이동했어요.',
    results: `${itemCount}개 제품 추천 결과 화면으로 이동했어요.`,
    compare: `${itemCount}개 제품 비교 화면으로 이동했어요.`,
    saved: `찜한 제품 ${itemCount}개 화면으로 이동했어요.`,
  };
  return labels[screen];
}
