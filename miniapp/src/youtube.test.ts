import { describe, expect, it } from 'vitest';
import { youtubePrivacyEnhancedEmbedUrl } from './youtube';

describe('youtubePrivacyEnhancedEmbedUrl', () => {
  it('builds a privacy-enhanced inline player URL that waits for a user tap', () => {
    const result = new URL(youtubePrivacyEnhancedEmbedUrl('abcDEF_123-'));

    expect(result.origin).toBe('https://www.youtube-nocookie.com');
    expect(result.pathname).toBe('/embed/abcDEF_123-');
    expect(result.searchParams.get('autoplay')).toBe('0');
    expect(result.searchParams.get('controls')).toBe('1');
    expect(result.searchParams.get('playsinline')).toBe('1');
    expect(result.searchParams.get('rel')).toBe('0');
    expect(result.searchParams.get('hl')).toBe('ko');
  });

  it.each([
    '',
    'too-short',
    'abcDEF_123-?autoplay=0',
    '../abcDEF_123-',
  ])('rejects an unsafe video ID: %s', (videoId) => {
    expect(() => youtubePrivacyEnhancedEmbedUrl(videoId)).toThrow(
      '올바른 YouTube 영상 ID가 아니에요.',
    );
  });
});
