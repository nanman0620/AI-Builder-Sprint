import { Redirect } from 'expo-router';

// 세션 확인 없이 "/"을 로그인 화면으로 고정 리다이렉트한다.
// 세션 상태에 따른 실제 분기는 후속 인증 Issue에서 이 파일을 교체해 구현한다.
export default function Index() {
  return <Redirect href="/(auth)/login" />;
}
