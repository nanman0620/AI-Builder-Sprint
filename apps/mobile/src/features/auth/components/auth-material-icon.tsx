import MaterialIcons from '@expo/vector-icons/MaterialIcons';
import { useEffect } from 'react';
import { Text, type StyleProp, type TextStyle } from 'react-native';

type MaterialIconName = keyof typeof MaterialIcons.glyphMap;

type AuthMaterialIconProps = {
  name: MaterialIconName;
  size: number;
  color: string;
  style?: StyleProp<TextStyle>;
};

export function AuthMaterialIcon({ name, size, color, style }: AuthMaterialIconProps) {
  const glyph = MaterialIcons.glyphMap[name];

  useEffect(() => {
    void MaterialIcons.loadFont();
  }, []);

  return (
    <Text
      allowFontScaling={false}
      aria-hidden
      selectable={false}
      style={[
        {
          color,
          fontFamily: MaterialIcons.getFontFamily(),
          fontSize: size,
          fontStyle: 'normal',
          fontWeight: 'normal',
        },
        style,
      ]}>
      {typeof glyph === 'number' ? String.fromCodePoint(glyph) : glyph}
    </Text>
  );
}
