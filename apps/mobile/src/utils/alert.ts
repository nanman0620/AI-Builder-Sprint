import { Alert, Platform, type AlertButton } from 'react-native';

// react-native-web의 Alert.alert는 빈 함수(no-op)라 다이얼로그도 뜨지 않고 onPress도 절대
// 호출되지 않는다(node_modules/react-native-web/dist/exports/Alert/index.js 확인).
// onPress에 화면 전환·후속 처리가 담긴 호출부가 웹에서 멈춘 것처럼 보이는 원인이라, 웹에서는
// window.alert로 대체하고 버튼이 하나면 그 onPress를 직접 실행한다.
export function showAlert(title: string, message?: string, buttons?: AlertButton[]): void {
  if (Platform.OS !== 'web') {
    Alert.alert(title, message, buttons);
    return;
  }

  window.alert(message ? `${title}\n\n${message}` : title);
  if (buttons?.length === 1) {
    buttons[0].onPress?.();
  }
}
