import { defineConfig, type AppsInTossWebConfigResponse } from '@apps-in-toss/web-framework/config';

const config: AppsInTossWebConfigResponse = defineConfig({
  appName: 'k-beauty-agent',
  brand: {
    displayName: 'K뷰티에이전트',
    primaryColor: '#3182F6',
    icon: 'https://static.toss.im/appsintoss/60965/3ed9c583-09a5-4e8a-bf0c-36ffe4c86710.png',
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
