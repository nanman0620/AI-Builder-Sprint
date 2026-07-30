// 서버의 clientEventId 기반 멱등 처리(중복 전송 방지)를 위한 요청별 고유 값을 만든다.
// 보안 목적이 아니라 요청 구분용이므로 crypto 라이브러리 의존 없이 생성한다.
export function generateClientEventId(): string {
  const random = Math.random().toString(36).slice(2);
  const timestamp = Date.now().toString(36);
  return `${timestamp}-${random}`;
}
