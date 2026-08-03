// `app/_layout.tsx`의 useFonts로 로드되는 fontFamily 이름.
// 실제 폰트 파일: assets/fonts/Pretendard-*.otf (OFL-1.1, assets/fonts/PRETENDARD-LICENSE.txt),
// assets/fonts/Inter-SemiBold.ttf (OFL-1.1, assets/fonts/INTER-LICENSE.txt)
export const fonts = {
  regular: 'Pretendard-Regular',
  medium: 'Pretendard-Medium',
  semiBold: 'Pretendard-SemiBold',
  bold: 'Pretendard-Bold',
  interSemiBold: 'Inter-SemiBold',
} as const;
