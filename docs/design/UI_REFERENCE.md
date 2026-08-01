# 이음 MVP UI 구현 기준

이 문서는 전달받은 화면 캡처 32장과 이미지 조각·자산 33장을 최종 화면 흐름에 연결한 에이전트용 시각 인수인계다. 사용자가 수동으로 화면-코드 표를 작성할 필요는 없다.

## 1. 권한

| 판단 | 기준 |
| --- | --- |
| 화면 존재 여부, 상태, Route, 문구, 이동, API 호출, 오류 동작 | `이음_MVP_최종_화면_흐름.pdf` |
| 색상, 간격, 배치, 모서리, 그림자, 컴포넌트 외형 | 이 문서와 `ui/screens/` |
| 요청·응답 데이터 | 최종 API 명세서 |
| 저장·제약·Worker | 최종 DB 구조 |

캡처는 기능 계약이 아니다. 아래 보정 사항은 캡처와 최종 계약을 대조해 확정한 구현 규칙이다.

## 2. 반드시 보정할 차이

| 캡처 | 보이는 내용 | 구현 규칙 |
| --- | --- | --- |
| `UI-002` | 인증 실패를 비밀번호 단독 오류처럼 표시 | 형식은 참고하되 인증 실패 문구는 “이메일 또는 비밀번호를 확인해 주세요.”를 입력 영역 공통 오류로 표시 |
| `UI-005`~`UI-009` | 홈 우측 상단의 상점 진입 | 모든 `HomeHeader`에 상점 PNG를 표시하고 누르면 MVP 미지원 안내 모달만 연다. 상점 Route, API, 재화, 구매와 화면 이동은 구현하지 않음 |
| `UI-008`, `UI-009` | 3초 뒤 현재 계획으로 자동 이동 | 자동 이동·자동 acknowledgement 금지. 사용자가 `[현재 계획 보기]`를 눌렀을 때만 화면의 모든 `taskIds`를 일괄 확인 |
| `UI-022`~`UI-026` | 할 일 앞 원형 표시 | 캘린더는 조회 전용. 원형은 완료 상태 표시이며 터치 체크 컨트롤이 아님 |
| `UI-028`, `UI-029` | 이메일이 일반 입력창처럼 보임 | 이메일은 `auth.users.email` 읽기 전용. 이메일 변경 API를 만들지 않음 |
| `UI-032` | “연결에 실패했어요” 문구 | 레이아웃만 참고. 일반 최초 조회 오류는 “정보를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.” |
| 점수 25·75 조각 | 고정된 원형 게이지 이미지 | 점수는 0~100 동적 값이므로 코드로 그림. PNG import 금지 |
| 하단 탭·버튼·입력 조각 | 완성된 UI 이미지 | 코드 컴포넌트와 상태 variant로 구현. `reference-only/` import 금지 |

추가 규칙:

- 캡처의 닉네임, 이메일, 날짜, 할 일, 고정 일정, 점수는 예시 데이터다.
- 상태바 `9:41`, 배터리, 홈 인디케이터는 native 영역을 사용하고 직접 그리지 않는다.
- 카카오 로그인 표시는 캡처에서 잘라 쓰지 않고 공식 로그인 UI 또는 코드 컴포넌트를 사용한다.
- `UI-008`과 `UI-009`는 하나의 경고 목록 컴포넌트다. `items.length`만 달라진다.
- `UI-014`~`UI-016`은 하나의 `/plan-management` Route와 `COLLECTING / CHANGE_CONFIRMATION / CHANGE_INPUT` 데이터 variant다.
- 홈의 여섯 상태도 화면별 Route가 아니라 서버 `homeMode`와 `blockingNotice`에 따른 variant다.
- `HomeHeader`의 상점 아이콘은 왼쪽 날짜·제목·선택 설명의 실제 높이와 같게 표시한다. 모달은 제목 “상점은 아직 준비 중이에요”, 본문 “이번 MVP 버전에서는 상점 기능을 이용할 수 없어요. 추후 업데이트에서 만나보실 수 있습니다.”, `[확인]` 버튼을 사용하며 확인·배경 터치·Android 뒤로가기로 닫는다.
- 캡처와 이 표에 없는 새 충돌은 임의로 해결하지 말고 영향과 선택지를 보고한다.

## 3. 화면 매핑

### 인증·공통

| ID | 파일 | 상태 | 구현 메모 |
| --- | --- | --- | --- |
| UI-001 | `ui/screens/UI-001-splash.png` | 로고·초기 로딩 | 세션 확인과 `GET /bootstrap`; 실패 시 UI-032 스타일의 전체 오류 |
| UI-002 | `ui/screens/UI-002-login-auth-error.png` | 로그인·인라인 오류 | 기본 로그인도 같은 레이아웃. 이메일·비밀번호별 오류와 인증 공통 오류를 분리 |
| UI-003 | `ui/screens/UI-003-sign-up.png` | 회원가입 | 약관은 프론트 필수 검증만 하고 이력은 저장하지 않음 |
| UI-004 | `ui/screens/UI-004-onboarding-nickname.png` | 닉네임 생성 | 중복·글자 수 제한 없음, 공백만 거부 |
| UI-032 | `ui/screens/UI-032-common-network-error.png` | 전체 네트워크 오류 | 최종 표준 문구와 다시 시도 동작 사용 |

### 홈

| ID | 파일 | 서버 상태 | 구현 메모 |
| --- | --- | --- | --- |
| UI-005 | `ui/screens/UI-005-home-no-active-cycle.png` | `NO_ACTIVE_CYCLE` | 계획관리 `NEW_CYCLE_ENTRY`로 이동 |
| UI-006 | `ui/screens/UI-006-home-no-plans.png` | `NO_PLANS` | 현재 분기에 PlanBlock 없음; 홈 고정 일정 표시 금지 |
| UI-007 | `ui/screens/UI-007-home-in-progress.png` | `IN_PROGRESS` | 현재 분기의 `PLANNED / CHECKED`; 진행률은 개수 기준 |
| UI-008 | `ui/screens/UI-008-home-deadline-warning-multiple.png` | `blockingNotice=DEADLINE_WARNING`, 복수 | 동일 목록 컴포넌트, 스크롤 가능 |
| UI-009 | `ui/screens/UI-009-home-deadline-warning-single.png` | `blockingNotice=DEADLINE_WARNING`, 단일 | UI-008과 같은 컴포넌트 |
| UI-010 | `ui/screens/UI-010-home-finalizing.png` | `FINALIZING` | 하단 탭 없음; 조회 실패를 정산 실패로 해석하지 않음 |
| UI-011 | `ui/screens/UI-011-home-check-in-result.png` | `CHECK_IN_RESULT` | 완료·미완료 모두 표시; 점수·개수·목록은 응답 기반; 아래 점수 구간·배치 규칙에 따라 마스코트 추가 |

### 계획관리

| ID | 파일 | `screenMode` | 구현 메모 |
| --- | --- | --- | --- |
| UI-012 | `ui/screens/UI-012-plan-new-cycle-entry.png` | `NEW_CYCLE_ENTRY` | ACTIVE cycle이 없을 때 새 7일 입력 |
| UI-013 | `ui/screens/UI-013-plan-active-cycle-entry.png` | `ACTIVE_CYCLE_ENTRY` | 기존 계획 수정·추가 입력 |
| UI-014 | `ui/screens/UI-014-plan-collecting-initial.png` | `COLLECTING` | 최초 분석 결과 카드 |
| UI-015 | `ui/screens/UI-015-plan-collecting-clarification.png` | `COLLECTING` | 질문·답변·카드 갱신 |
| UI-016 | `ui/screens/UI-016-plan-change-input.png` | `CHANGE_CONFIRMATION / CHANGE_INPUT` | 같은 채팅 화면에서 quick reply와 입력 가능 상태만 변경 |
| UI-017 | `ui/screens/UI-017-plan-final-review.png` | `FINAL_REVIEW` | 수정 또는 모두 등록 |
| UI-018 | `ui/screens/UI-018-plan-executing.png` | `EXECUTING` | 하단 탭 표시, 다른 탭 이동 가능, 서버 작업 계속 |
| UI-019 | `ui/screens/UI-019-plan-execution-success.png` | `EXECUTION_SUCCESS` | 전체 화면, 하단 탭 없음, 결과 acknowledge 후 홈 |
| UI-020 | `ui/screens/UI-020-plan-execution-failed.png` | `EXECUTION_FAILED` | 서버가 실제 `FAILED`일 때만 표시 |
| UI-021 | `ui/screens/UI-021-plan-exit-confirmation.png` | 작성 중 나가기 오버레이 | DELETE 성공 전 이동 금지 |

- 계획관리 채팅의 사용자 메시지 버블은 왼쪽 `#A83DE2`에서 오른쪽 `#D279FE`로 이어지는 수평 그라데이션과 흰색 텍스트를 사용한다. Assistant 메시지 버블은 기존 `primarySoft` 단색 배경을 유지한다.

### 캘린더

| ID | 파일 | variant | 구현 메모 |
| --- | --- | --- | --- |
| UI-022 | `ui/screens/UI-022-calendar-zero-score.png` | 실제 score 0 | CheckIn이 있고 `score=0`일 때만 0점 표시 |
| UI-023 | `ui/screens/UI-023-calendar-future.png` | 미래 | 미래 분기의 완료 개수·0% 영역을 만들지 않음 |
| UI-024 | `ui/screens/UI-024-calendar-empty.png` | 통합 빈 상태 | 할 일·고정 일정·CheckIn이 모두 없음; 이동 버튼 없음 |
| UI-025 | `ui/screens/UI-025-calendar-mixed-day.png` | 현재 날짜의 과거·현재 분기 혼합 | 각 분기의 실제 시점 규칙 적용 |
| UI-026 | `ui/screens/UI-026-calendar-past-day.png` | 과거 | `COMPLETED`만 표시하고 `NOT_DONE`은 숨김 |

- 캘린더 분기 헤더 오른쪽에는 과거 분기의 실제 `CheckIn.score`와 현재 분기의 `CHECKED / (PLANNED + CHECKED)` 개수 비율을 원형 게이지로 표시한다. 실제 과거 score 0은 0으로 표시하고, 현재 분기에 PlanBlock이 없거나 미래 분기이면 게이지를 표시하지 않는다.
- 분기 헤더의 점수 텍스트 접미사(`· N점`)는 사용하지 않고 게이지 중앙에 반올림한 숫자만 표시한다.

### 설정

| ID | 파일 | 상태 | 구현 메모 |
| --- | --- | --- | --- |
| UI-027 | `ui/screens/UI-027-settings-menu.png` | 설정 메뉴 | `GET /me` 프로필 |
| UI-028 | `ui/screens/UI-028-settings-profile.png` | 개인정보 수정 | 닉네임만 실제 변경; 이메일 읽기 전용; 비밀번호 시연용 |
| UI-029 | `ui/screens/UI-029-settings-profile-saved.png` | 저장 완료 토스트 | 실제 닉네임 저장과 프론트 비밀번호 검증 성공 뒤 표시 |
| UI-030 | `ui/screens/UI-030-settings-logout-modal.png` | 로그아웃 오버레이 | 배경과 하단 탭 유지, 탭 입력 비활성화 |
| UI-031 | `ui/screens/UI-031-settings-account-withdrawal.png` | 회원탈퇴 확인 | 실제 계정·DB 삭제 없이 로컬 초기화와 signOut |

## 4. 이미지 자산

이 agent-kit이 제품 화면용 runtime brand 자산으로 추가하는 파일은 다음 아홉 개다. 기존 Expo 프로젝트의 앱 아이콘·스플래시 등 설정 자산은 이 제한 대상이 아니며, 삭제하거나 사용 금지 대상으로 해석하지 않는다.

| 파일 | 용도 |
| --- | --- |
| `../../apps/mobile/assets/brand/eum-logo.png` | 단독 로고 |
| `../../apps/mobile/assets/brand/eum-logo-tagline.png` | 로고와 캐치프레이즈 |
| `../../apps/mobile/assets/brand/mascot-default.png` | 기본·성공·진행 상태 |
| `../../apps/mobile/assets/brand/mascot-reading.png` | 계획 없음·새 계획 안내 |
| `../../apps/mobile/assets/brand/mascot-sad.png` | 오류·마감 경고·실패 |
| `../../apps/mobile/assets/brand/mascot-score-00.png` | CheckIn `score` 0~29 |
| `../../apps/mobile/assets/brand/mascot-score-30.png` | CheckIn `score` 30~59 |
| `../../apps/mobile/assets/brand/mascot-score-60.png` | CheckIn `score` 60~99 |
| `../../apps/mobile/assets/brand/mascot-score-100.png` | CheckIn `score` 100 |

상대 경로는 이 문서 위치 기준 설명이다. 실제 TypeScript import는 `apps/mobile`의 alias와 기존 구조를 확인해 작성한다.

### 점수별 마스코트 선택 규칙

```text
0 <= score < 30    → mascot-score-00.png
30 <= score < 60   → mascot-score-30.png
60 <= score < 100  → mascot-score-60.png
score = 100        → mascot-score-100.png
```

- 이 규칙은 `CHECK_IN_RESULT`의 시각 자산 선택에만 사용한다.
- 점수 게이지는 계속 `score` 값으로 코드에서 동적으로 그리며, 게이지 조각 PNG를 import하지 않는다.
- 30점 경계는 표정 변화만 위한 시각 규칙이다. 피드백 문구는 최종 화면 흐름의 60점 기준을 따른다. 100점은 마스코트 최고 단계 자산 선택 경계일 뿐 별도의 피드백 정책 기준이 아니다.
- 재계획 여부는 점수 구간이 아니라 `NOT_DONE` PlanBlock 존재 여부로 결정한다.
- 100점도 일반 피드백에서는 `score >= 60`에 포함되므로 기존 긍정적 피드백 문구를 사용한다.
- 서버 API·DB에 마스코트 이름이나 별도 상태 컬럼을 추가하지 않고 모바일에서 `score`로 파생한다.
- Expo/Metro 호환성을 위해 파일명 문자열을 조합한 동적 `require()`를 사용하지 않는다. 네 자산을 각각 정적으로 import 또는 require한 명시적 매핑을 사용한다.

### `CHECK_IN_RESULT` 피드백 우선순위

1. `cycleEnded = true`이면 7일 계획 종료 문구를 사용한다.
2. `cycleEnded = false AND score >= 60`이면 긍정적 피드백 문구를 사용한다.
3. `cycleEnded = false AND score < 60`이면 놓친 계획을 다시 이어두었다는 안내 문구를 사용한다.

`cycleEnded = true`이면 점수에 따른 일반 피드백보다 계획 종료 문구를 우선한다.

### `CHECK_IN_RESULT` 마스코트 배치 규칙

`UI-011` 캡처에는 마스코트가 없지만 실제 구현에는 아래 규칙으로 추가한다.

- 배치 순서는 `결과 제목·점수 게이지 → 점수별 이음이 마스코트 → 완료·미완료 개수 → 완료·미완료 PlanBlock 목록`이다.
- 마스코트는 점수 게이지를 대체하지 않고 별도 요소로 유지한다.
- 화면 가운데에 정렬하고 마스코트 표시 영역은 128dp × 128dp로 고정한다.
- React Native `Image`는 `resizeMode="contain"`, Expo Image는 `contentFit="contain"`을 사용한다.
- 결과 목록은 기존처럼 스크롤 가능하게 유지한다.

## 5. 코드 연결 기록 시점

적용 대상 저장소의 코드 구조를 가정해 화면-파일 경로를 미리 고정하지 않는다. 실제 UI Issue에서 에이전트가 기존 Route·Screen·Component 구조를 확인한 뒤 구현하고, PR의 화면 변경 절에 다음만 기록한다.

- 사용한 UI ID
- 구현한 Route와 상태
- 새로 만들거나 수정한 코드 파일
- 캡처와 의도적으로 다르게 구현한 항목
- 실제 에뮬레이터 검수 결과
