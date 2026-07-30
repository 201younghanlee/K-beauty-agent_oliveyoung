import { defineConfig, type AppsInTossWebConfigResponse } from '@apps-in-toss/web-framework/config';

const config: AppsInTossWebConfigResponse = defineConfig({
  appName: 'k-beauty-agent',
  brand: {
    displayName: '뷰티인덱스',
    primaryColor: '#3182F6',
    icon: 'https://static.toss.im/appsintoss/60965/24e162a5-d6b0-45d4-a02c-83a037a41e3a.png',
  },
  web: {
    host: 'localhost',
    port: 5173,
    commands: {
      dev: 'vite --host 0.0.0.0',
      build: 'tsc -b && vite build',
    },
  },
  permissions: [],
  navigationBar: {
    withBackButton: true,
    withHomeButton: true,
  },
  outdir: 'dist',
  webViewProps: {
    type: 'partner',
    allowsInlineMediaPlayback: true,
    mediaPlaybackRequiresUserAction: true,
  },
});

export default config;
