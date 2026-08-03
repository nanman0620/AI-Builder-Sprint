# UI 이미지 사용 규칙

## 폴더

- `screens/`: 최종 화면의 시각 배치·스타일 참고용 캡처
- `reference-only/`: 버튼·입력창·탭·게이지 등 코드 컴포넌트 참고용 조각
- `apps/mobile/assets/brand/`: 앱 bundle에서 실제로 사용할 수 있는 로고·마스코트 PNG와 승인된 상점 진입 아이콘. CheckIn 점수별 마스코트 네 장 포함
- `apps/mobile/assets/images/`: Expo 설정 이미지와 승인된 하단 탭 상태 PNG 여덟 장. 탭 PNG는 `reference-only/` 원본을 runtime 위치로 복사한 명시적 예외

화면과 상태의 전체 매핑은 상위 `UI_REFERENCE.md`를 따른다.

## 금지

- `screens/` 이미지를 앱 화면 배경으로 사용하지 않는다.
- `reference-only/` 경로의 파일을 React Native에서 직접 import하지 않는다.
- 아래 승인된 하단 탭 상태 PNG 여덟 장 외에는 버튼, 카드, 입력창, 탭, 체크박스, 점수 게이지, 캘린더를 PNG로 구현하지 않는다.
- 캡처의 상태바·홈 인디케이터·예시 데이터·스크롤바를 이미지로 복제하지 않는다.

## 구현

- 레이아웃, 텍스트, 배경, 테두리, 그림자와 상태 variant는 React Native 코드로 만든다.
- 점수 게이지는 `score` 값으로 동적으로 그린다.
- CheckIn 마스코트는 `UI_REFERENCE.md`의 `0~29`, `30~59`, `60~99`, `100` 구간으로 runtime asset을 선택한다.
- 30점은 표정 선택 전용, 60점은 결과 피드백 문구 선택 전용, 100점은 최고 단계 마스코트 선택 전용이며, 실제 재계획 여부는 `NOT_DONE` 존재 여부로 결정한다. 100점도 `score >= 60`의 기존 긍정적 피드백을 사용한다.
- 하단 탭은 `apps/mobile/assets/images/`의 `REF-005`, `REF-006`, `REF-011`, `REF-012`, `REF-018`, `REF-019`, `REF-023`, `REF-024` PNG만 runtime에서 사용할 수 있다. 파일명과 선택·기본 상태 매핑은 유지한다.
- 하단 탭 외의 표준 아이콘은 프로젝트가 채택한 아이콘 컴포넌트를 사용한다.
- 카카오 로그인 표시는 캡처를 잘라 쓰지 않고 공식 로그인 UI 또는 코드 컴포넌트를 사용한다.
- 로고와 마스코트, `shop-entry-icon.png` 예외 자산만 `apps/mobile/assets/brand/`에서 사용한다. 상점 아이콘은 안내 모달 전용이며 Route·API와 연결하지 않는다.
- Safe Area와 native status bar를 사용하며 535px 캡처 크기를 고정 화면 폭으로 사용하지 않는다.
