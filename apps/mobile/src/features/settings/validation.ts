export function validateNickname(nickname: string): string | null {
  return nickname.trim().length === 0 ? '닉네임을 입력해 주세요.' : null;
}

export function validatePassword(password: string, passwordConfirm: string): string | null {
  if (!password && !passwordConfirm) {
    return null;
  }
  if (password && !passwordConfirm) {
    return '비밀번호 확인 입력칸에\n비밀번호를 다시 입력해 주세요.';
  }
  if (!password && passwordConfirm) {
    return '새 비밀번호 입력칸에\n새 비밀번호를 입력해 주세요.';
  }
  if (password !== passwordConfirm) {
    return '비밀번호가 일치하지 않아요.';
  }
  return null;
}
