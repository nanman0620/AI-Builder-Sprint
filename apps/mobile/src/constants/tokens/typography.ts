// 캡처 속 화면 제목·본문·보조 문구의 상대적 크기 비율을 기준으로 한 근사값이며, Figma 실측값이 아니다.
export const typography = {
  title: {
    fontSize: 19,
    fontWeight: '700',
    lineHeight: 28,
  },
  body: {
    fontSize: 15,
    fontWeight: '400',
    lineHeight: 22,
  },
  caption: {
    fontSize: 13,
    fontWeight: '400',
    lineHeight: 18,
  },
} as const;
