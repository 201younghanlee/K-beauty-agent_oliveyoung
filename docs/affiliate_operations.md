# Affiliate and Apps in Toss operations

## Platform boundary

The mini-app must finish its declared recommendation and comparison function
inside Toss. A retailer button may then open the directly relevant product page.
It must not require another app installation, use an unrelated promotional
landing page, or describe external checkout as a mini-app function.

Apps in Toss explicitly lists a product recommendation/lowest-price service as
an allowed external-link example, but its public documentation does not
explicitly approve every affiliate network, redirector, or sub-ID format.
Before launch, retain written approval from the Apps in Toss channel for the
exact redirect and tracking design.

- External-link policy: <https://developers-apps-in-toss.toss.im/checklist/miniapp-external-link.html>
- In-app ad policy: <https://developers-apps-in-toss.toss.im/ads/develop.html>
- Business verification: <https://developers-apps-in-toss.toss.im/prepare/console-workspace.html>

Suggested review request:

> 여러 타사 쇼핑몰의 화장품을 성분 기준으로 추천한 뒤 affiliate 링크로
> 해당 판매처 상품 페이지를 여는 서비스입니다. 추천과 비교는 미니앱 안에서
> 완결되고 주문·결제·배송은 판매처가 담당합니다. 구매 발생 시 수수료를 받을
> 수 있다는 사실을 각 상품 카드와 판매처 선택 화면에 표시합니다. 서명된 자체
> 리디렉트와 판매처가 승인한 campaign/sub-ID 사용이 가능한지 확인 부탁드립니다.

## Required disclosure

Place a visible `광고·제휴` label and the applicable Korean disclosure next
to every monetized retailer choice, not only in terms or a footer. Coupang's
official guide recommends:

> 이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.

For other networks, use the wording required by that network while still
making the economic relationship immediately clear.

The result page should also state:

> 추천 점수와 제품 순위에는 제휴 수수료를 사용하지 않습니다.

Only display the ranking sentence while the implementation actually enforces
that invariant. Paid placement belongs in a visually separate `광고` slot.

The current Korean Fair Trade Commission guideline requires a conditional
commission relationship to be disclosed clearly and close to each
recommendation:
<https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2100000280130&chrClsCd=010201>

## Partner activation checklist

1. Complete business registration and Apps in Toss business verification.
2. Join one domestic program first. Coupang Partners is preferred because it
   supports portal-created product links and, after final approval, product,
   deep-link, and reporting APIs for websites/apps.
3. Join Olive Young Shopping Curator for approved links, but treat it as a
   link-only source unless Olive Young grants a product feed/API agreement.
4. Add global feeds only after approval from a network such as Awin or
   Commission Factory. Store the feed's retention, image, and caching terms.
5. Before API access is available, generate product links in the Coupang
   Partners portal and store an exact product mapping in Render:
   `COUPANG_PARTNERS_LINKS_JSON=[{"product_id":"catalog-product-id","affiliate_url":"https://link.coupang.com/..."}]`.
   For Git-managed approved links, set
   `COUPANG_PARTNERS_LINKS_FILE=data/coupang_partner_links.json` instead.
   A regular Coupang or share URL is not a monetized replacement.
6. After Apps in Toss approves the disclosed external-link design, activate
   portal links with `ACTIVE_AFFILIATE_SOURCE_IDS=coupang_partner_links`.
   Show the required Korean disclosure with every active Coupang offer:
   `이 포스팅은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다.`
7. Register every activity page and a screenshot showing the link plus the
   disclosure in Coupang Partners. Complete Coupang's final-approval process.
8. Only after final approval, register API keys in Render secrets. Never paste
   or commit them.
9. Configure exact feed and retailer-domain allowlists.
10. Run a sandbox ingestion through the protected admin source API and review unmatched variants and abnormal prices.
11. Configure the scheduled sync secrets only after the manual sandbox succeeds.
12. Add `coupang_partners` to `ACTIVE_AFFILIATE_SOURCE_IDS` only after the API
    disclosure and redirect audit pass; then remove superseded manual mappings.
13. Import conversions only from a signed callback or approved network report.
14. Re-check program terms and Apps in Toss approval whenever the redirect,
    attribution parameters, or destination experience changes.

Official program references:

- Coupang Partners guide: <https://partners.coupangcdn.com/partners-guide/partners-guide-20250324160743.pdf>
- Olive Young Shopping Curator: <https://m.oliveyoung.co.kr/m/mtn/affiliate/guide>
- YesStyle affiliate program: <https://www.yesstyle.com/en/affiliate-program.html>
- StyleKorean affiliate terms: <https://www.stylekorean.com/en/affiliate/faq>
- Naver Shopping API shutdown: <https://developers.naver.com/notice/article/32564>

## Privacy and analytics

Affiliate sub-IDs may contain a random click ID, product/offer identifier,
placement, and campaign. Do not send:

- Toss user keys, email addresses, phone numbers, or raw session IDs;
- the user's free-text query;
- allergies, pregnancy/nursing status, skin concerns, or other health-linked
  profile values; or
- any stable cross-service identifier not expressly covered by consent.

Retain clicks only for the documented attribution and fraud-review period.
Delete or aggregate them afterwards. Update the privacy policy before enabling
production tracking.

The current redirect ledger creates an internal random click ID but does not
append that ID to a partner URL. Use a network sub-ID only after the network's
approved link contract and callback format are implemented and reviewed.

The optional normalized callback is `POST /api/integrations/affiliate/conversions`.
It accepts at most 64 KiB of JSON and verifies `X-Affiliate-Timestamp` plus
`X-Affiliate-Signature`, where the signature is an HMAC-SHA256 hex digest over
`<unix_timestamp>.<exact_request_body>` using `AFFILIATE_WEBHOOK_SECRET`.
Timestamps outside five minutes are rejected and external conversion IDs are
idempotent. `order_amount` and `commission_amount` are non-negative integer
minor units: KRW uses won, while USD uses cents. Fractional JSON numbers are
rejected instead of rounded or truncated. Do not expose this secret to the
browser or reuse the redirect key. The normalized schema rejects every unknown
field and stores no free-form partner metadata, customer identity, address, or
order-line detail. Conversion rows are eligible for deletion after 180 days by
the application cleanup; configure the daily protected maintenance workflow so
that deletion does not depend only on user traffic. Confirm the partner contract
and applicable accounting retention requirements before changing that period.
