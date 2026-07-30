export const MIN_PASSWORD_LENGTH = 8;

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function validateEmail(email: string): string | null {
  if (email.trim().length === 0) {
    return '이메일을 입력해 주세요.';
  }
  if (!EMAIL_PATTERN.test(email.trim())) {
    return '이메일이 올바르지 않아요.';
  }
  return null;
}

export function validateLoginPassword(password: string): string | null {
  if (password.length === 0) {
    return '비밀번호를 입력해 주세요.';
  }
  return null;
}

export function validateSignUpPassword(password: string): string | null {
  if (password.length === 0) {
    return '비밀번호를 입력해 주세요.';
  }
  if (password.length < MIN_PASSWORD_LENGTH) {
    return '비밀번호 조건을 확인해 주세요.';
  }
  return null;
}

export function validatePasswordConfirm(password: string, passwordConfirm: string): string | null {
  if (passwordConfirm.length === 0) {
    return '비밀번호를 다시 입력해 주세요.';
  }
  if (password !== passwordConfirm) {
    return '비밀번호가 일치하지 않아요.';
  }
  return null;
}

export function validateTerms(agreed: boolean): string | null {
  if (!agreed) {
    return '약관에 동의해 주세요.';
  }
  return null;
}
