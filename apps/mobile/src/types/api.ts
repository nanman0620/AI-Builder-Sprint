// docs/ai/IMPLEMENTATION_CONTEXT.md 3절의 공통 응답 규칙만 담는다.
// Task, PlanBlock, Cycle, SolarRequest 등 도메인별 DTO는 이 Issue의 범위가 아니다.
export type ApiSuccess<T> = {
  data: T;
};

export type ApiErrorBody = {
  code: string;
  message: string;
  details: unknown;
  traceId: string | null;
};

export type ApiFailure = {
  error: ApiErrorBody;
};
