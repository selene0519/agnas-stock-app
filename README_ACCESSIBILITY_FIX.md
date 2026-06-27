# MONE Accessibility/UI Patch

적용 파일:
- mone-web-app/frontend/components/BottomNav.tsx
- mone-web-app/frontend/components/SymbolSearchSelect.tsx
- mone-web-app/frontend/components/pages/HomePage.tsx
- mone-web-app/frontend/app/globals.css

반영 내용:
- BottomNav 더보기 시트 dialog semantics, Esc 닫기, 간단 focus trap, 닫기 버튼 44px 확대, aria-current 추가
- SymbolSearchSelect 검색 input label/name/autoComplete 추가, 지우기 버튼 터치 영역 44px 확대
- HomePage 포지션 자본금 input label/name/autoComplete 추가, 후보 이동점 터치 영역 44px 확대, 빈 보유종목 이모지 아이콘을 Lucide ClipboardList로 교체
- globals.css transition: all 제거, input focus-visible 강조, skip-link/helper focus 스타일 추가

주의:
- 업로드된 zip은 경로가 일부 평탄화되어 app/page.tsx 메인 파일을 안전하게 식별할 수 없어, app/page.tsx의 알림 dialog/skip link 수정은 포함하지 않았습니다.
- 적용 후 npm run build로 확인하세요.
