# Video review card design QA

- Reference source: `/var/folders/p4/g_24zxsx74d6zf2c1lm111040000gn/T/TemporaryItems/NSIRD_screencaptureui_lABm1q/스크린샷 2026-07-23 오후 12.02.21.png`
- Reference size: `624 × 724`
- Implementation screenshot: `design-qa-mobile.png`
- Implementation viewport: `390 × 844`
- Core-card comparison: `design-qa-comparison.png`
- Comparison method: the implementation's preview, statistics row, and channel panel were normalized to the reference's `522px` content width and placed beside the source image.

## Visual checks

- 16:9 thumbnail fills the available width without stretching.
- The original video title, channel name, and YouTube thumbnail remain visible.
- A centered red play affordance opens the canonical YouTube watch URL.
- View count, like count, and publication date form one compact row.
- Channel avatar, channel name, subscriber count, and the black primary CTA match the reference hierarchy.
- The card stays inside a `390px` mobile viewport with no horizontal overflow.
- Missing optional metrics or channel imagery degrade cleanly without breaking the card.
- YouTube policy details remain available below the primary experience without dominating it.

## Iterations

1. Replaced the manual load control with automatic loading for the first recommendation and viewport-triggered loading for the remaining products.
2. Rebuilt the small result list as a full-width video preview, statistics row, channel panel, and primary CTA.
3. Increased statistics, channel-title, panel-padding, and CTA sizing after the first side-by-side comparison.
4. Re-captured at `390 × 844` and compared the core card at the same content width as the source.

final result: passed
