MONE loading screen patch

Modified / added:
- components/AppLaunchLoading.tsx
- app/page.tsx
- public/loading/mone-logo.png
- public/loading/mone-bear.png

Behavior:
- Shows boot loading overlay on first app mount only.
- Checks health, KR/US data-quality, KR/US recommendations.
- Shows delayed message after 10 seconds.
- Does not block app entry when API checks fail.
- Existing page routing, API adapters, and chart/data logic are not changed.

Apply:
1. Extract this zip at C:\dev\agnas-stock-app\mone-web-app\frontend or repo root depending on your workflow.
2. Run: npm run build
3. Commit only the files listed above.
