import { describe, expect, it } from 'vitest';
import { routeAnnouncement } from './accessibility';

describe('routeAnnouncement', () => {
  it('announces loading and each SPA destination with useful context', () => {
    expect(routeAnnouncement('survey', true, 0)).toBe('추천 제품을 분석하고 있어요.');
    expect(routeAnnouncement('results', false, 5)).toBe('5개 제품 추천 결과 화면으로 이동했어요.');
    expect(routeAnnouncement('compare', false, 2)).toBe('2개 제품 비교 화면으로 이동했어요.');
    expect(routeAnnouncement('saved', false, 3)).toBe('찜한 제품 3개 화면으로 이동했어요.');
  });
});
