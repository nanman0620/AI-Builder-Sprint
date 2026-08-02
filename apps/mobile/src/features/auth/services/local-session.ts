// 회원탈퇴 시 signOut(scope:'local')이 실패했을 때만 쓰는 fallback. auth-service.ts와 별도
// 파일로 분리한 이유: auth-service.ts는 expo-linking/expo-web-browser(Kakao OAuth 콜백 파싱)를
// 임포트하는데, 그 의존성 체인의 expo-modules-core가 컴파일되지 않은 .ts를 그대로 배포해
// node --test(플레인 Node)로는 아예 로드가 안 된다. 이 파일은 AsyncStorage와
// SUPABASE_AUTH_STORAGE_KEY만 써서 순수 Node 환경에서도 테스트할 수 있다.
import AsyncStorage from '@react-native-async-storage/async-storage';

import { SUPABASE_AUTH_STORAGE_KEY } from '@/src/services/supabase/client';

// PKCE 흐름에서 code-verifier를 저장하는 보조 키(auth-js lib/helpers.js의
// `${storageKey}-code-verifier` 관례). 이 두 키 외에 다른 sb-* 키(다른 프로젝트·클라이언트가
// 쓸 수 있는)는 절대 건드리지 않는다.
const AUTH_CODE_VERIFIER_KEY = `${SUPABASE_AUTH_STORAGE_KEY}-code-verifier`;

export async function forceClearLocalSession(): Promise<void> {
  await AsyncStorage.multiRemove([SUPABASE_AUTH_STORAGE_KEY, AUTH_CODE_VERIFIER_KEY]);
}

export async function isLocalSessionCleared(): Promise<boolean> {
  const entries = await AsyncStorage.multiGet([SUPABASE_AUTH_STORAGE_KEY, AUTH_CODE_VERIFIER_KEY]);
  return entries.every(([, value]) => value === null);
}
