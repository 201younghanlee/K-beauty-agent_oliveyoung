const YOUTUBE_VIDEO_ID_PATTERN = /^[0-9A-Za-z_-]{11}$/;

export function youtubePrivacyEnhancedEmbedUrl(videoId: string): string {
  if (!YOUTUBE_VIDEO_ID_PATTERN.test(videoId)) {
    throw new Error('올바른 YouTube 영상 ID가 아니에요.');
  }

  const params = new URLSearchParams({
    autoplay: '0',
    controls: '1',
    playsinline: '1',
    rel: '0',
    hl: 'ko',
  });
  return `https://www.youtube-nocookie.com/embed/${videoId}?${params.toString()}`;
}
