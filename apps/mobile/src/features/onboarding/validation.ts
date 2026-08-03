export function validateNickname(rawNickname: string): string | null {
  if (rawNickname.trim().length === 0) {
    return '닉네임을 입력해 주세요.';
  }
  return null;
}
