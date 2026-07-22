# K뷰티에이전트 · Apps in Toss 미니앱

기존 K-Beauty Agent 추천 API를 앱인토스 WebView SDK 2.x에서 사용하는 React + TypeScript + Vite 프런트엔드입니다. 로그인이나 쿠키에 의존하지 않고, 익명 세션 토큰을 `X-KBeauty-Session` 헤더로 보냅니다.

## 로컬 실행

Node.js 24 이상과 pnpm이 필요합니다.

```bash
cp .env.example .env
pnpm install
pnpm dev
```

웹 브라우저 UI만 빠르게 확인하려면 `pnpm dev:web`을 실행합니다. 앱인토스 QR 테스트는 `.ait` 업로드 후 발급된 배포 ID를 넣은 `intoss-private://k-beauty-agent?_deploymentId=<deploymentId>` 딥링크로 접속합니다.

API 주소를 바꾸려면 `.env`의 값을 수정합니다.

```dotenv
VITE_API_BASE_URL=https://k-beauty-recommendation-agent-gafd.onrender.com
```

## 앱인토스 번들 만들기

```bash
pnpm typecheck
pnpm build
```

`pnpm build`는 SDK 2.x의 `ait build`를 실행하고, `granite.config.ts` 안의 `web.commands.build`를 통해 TypeScript와 Vite 빌드를 먼저 검증합니다. 생성된 `.ait` 파일을 앱인토스 콘솔에 업로드합니다.

맞춤 기록은 일반 개인정보 처리 동의 후에만 서버에 저장됩니다. 공개 앱은
알레르기·임신·수유·질환 자유문장을 받지 않고, 원문 대신 허용된 퀴즈 선택과
형식 검사를 통과한 성분명만 저장합니다. 이메일·전화번호·URL·메모형 문장은
성분명 입력으로 허용하지 않습니다. 기기 찜 캐시는 마지막 앱 사용 후 30일에 만료되며
`내 데이터 삭제`가 서버 데이터와 로컬 저장소를 함께 지웁니다.

## 콘솔 설정

다음 값은 `granite.config.ts`와 동일해야 합니다.

- appName: `k-beauty-agent`
- 표시 이름: `K뷰티에이전트`
- 앱 유형: 비게임 (`partner`)
- 권한: 없음
- 기본 색상: `#3182F6`

`brand.icon`은 앱인토스 콘솔에 등록한 600×600 PNG 기본 로고의 토스 이미지 URL과 동일하게 유지합니다.

QR 테스트 딥링크는 `intoss-private://k-beauty-agent?_deploymentId=<deploymentId>`, 출시 딥링크는 `intoss://k-beauty-agent`입니다. `<deploymentId>`는 `.ait`를 콘솔에 업로드하거나 `ait deploy`를 실행한 뒤 발급된 배포 ID를 사용합니다.

## 백엔드 요구사항

앱인토스의 다음 origin을 CORS 허용 목록에 포함해야 합니다.

- `https://k-beauty-agent.apps.tossmini.com`
- `https://k-beauty-agent.private-apps.tossmini.com`

API는 HTTPS로 제공되어야 하고, `Content-Type` 및 `X-KBeauty-Session` 요청 헤더를 허용해야 합니다. 추천 요청은 다음 계약을 사용합니다.

```json
{
  "query": "지성 피부에 맞는 선크림을 추천해줘...",
  "limit": 5,
  "use_openai": false,
  "language": "ko",
  "profile": {
    "skin_type": "oily",
    "concerns": ["oil_control"],
    "desired_categories": ["sunscreen"],
    "avoid_ingredients": ["fragrance"],
    "max_price_krw": 30000
  }
}
```

익명 세션 토큰은 앱인토스 `Storage`를 먼저 사용하고, SDK 브리지가 없는 일반 브라우저에서는 `localStorage`로 대체합니다. API 요청에는 `credentials: "omit"`을 사용하므로 iOS의 서드파티 쿠키 제한과 무관하게 기본 추천 기능이 작동합니다. 찜한 제품은 기기의 `localStorage`에 저장됩니다.

## 구현된 흐름

- 피부 타입, 제품군, 피부 고민, 제형, 예산, 피할 성분 설문
- 한국어 추천 요청 및 응답 계약 차이 정규화
- 추천 근거, 성분, 주의사항, 가격을 담은 제품 카드
- 로컬 찜 목록, 조건 변경 재검색, 로딩·오류·빈 결과 화면
- 앱인토스 `SafeAreaInsets`, `openURL`, `Storage` 연동과 일반 브라우저 fallback

제품 추천은 정보 제공 목적이며 의학적 진단이 아닙니다. 민감 피부나 알레르기가 있는 사용자는 구매 전 전성분 확인과 패치 테스트가 필요합니다.
