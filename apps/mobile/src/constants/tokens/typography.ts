import { fonts } from './fonts';

// 캡처 속 화면 제목·본문·보조 문구의 상대적 크기 비율을 기준으로 한 근사값이며, Figma 실측값이 아니다.
// fontFamily가 이미 특정 웨이트 파일(Pretendard-*)을 가리키므로 fontWeight는 넣지 않는다.
// 이 값 위에 fontWeight를 덧씌우면 커스텀 폰트에 합성 볼드가 걸릴 수 있으니
// 다른 웨이트가 필요하면 fontFamily를 fonts.medium/semiBold/bold로 덮어쓴다.
export const typography = {
  title: {
    fontSize: 20,
    fontFamily: fonts.bold,
    lineHeight: 28,
  },
  body: {
    fontSize: 15,
    fontFamily: fonts.regular,
    lineHeight: 22,
  },
  caption: {
    fontSize: 13,
    fontFamily: fonts.regular,
    lineHeight: 18,
  },
} as const;
