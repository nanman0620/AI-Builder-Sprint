function required(name: string, value: string | undefined): string {
  if (!value) {
    throw new Error(`환경변수 ${name}가 설정되지 않았습니다. .env.example을 참고해 .env를 구성하세요.`);
  }
  return value;
}

export const env = {
  get supabaseUrl() {
    return required('EXPO_PUBLIC_SUPABASE_URL', process.env.EXPO_PUBLIC_SUPABASE_URL);
  },
  get supabaseAnonKey() {
    return required('EXPO_PUBLIC_SUPABASE_ANON_KEY', process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY);
  },
  get apiBaseUrl() {
    return required('EXPO_PUBLIC_API_BASE_URL', process.env.EXPO_PUBLIC_API_BASE_URL);
  },
};
