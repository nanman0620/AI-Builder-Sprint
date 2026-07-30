import { colors } from '@/src/constants/tokens';

type ColorName = 'text' | 'background';

export function useThemeColor(props: { light?: string; dark?: string }, colorName: ColorName) {
  return props.light ?? props.dark ?? colors[colorName];
}
