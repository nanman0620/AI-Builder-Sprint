import { StyleSheet, Text, type TextProps } from 'react-native';

import { colors, typography } from '@/src/constants/tokens';
import { useThemeColor } from '@/src/hooks/use-theme-color';

export type ThemedTextProps = TextProps & {
  lightColor?: string;
  darkColor?: string;
  type?: 'default' | 'title' | 'defaultSemiBold' | 'subtitle' | 'link';
};

export function ThemedText({
  style,
  lightColor,
  darkColor,
  type = 'default',
  ...rest
}: ThemedTextProps) {
  const color = useThemeColor({ light: lightColor, dark: darkColor }, 'text');

  return (
    <Text
      style={[
        { color },
        type === 'default' ? styles.default : undefined,
        type === 'title' ? styles.title : undefined,
        type === 'defaultSemiBold' ? styles.defaultSemiBold : undefined,
        type === 'subtitle' ? styles.subtitle : undefined,
        type === 'link' ? styles.link : undefined,
        style,
      ]}
      {...rest}
    />
  );
}

const styles = StyleSheet.create({
  default: typography.body,
  defaultSemiBold: { ...typography.body, fontWeight: '700' },
  title: typography.title,
  subtitle: { ...typography.body, fontWeight: '700' },
  link: { ...typography.body, color: colors.primary },
});
