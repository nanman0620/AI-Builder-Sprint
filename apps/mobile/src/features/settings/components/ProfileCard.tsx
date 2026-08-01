import { LinearGradient } from 'expo-linear-gradient';
import { Image, StyleSheet, Text, View } from 'react-native';

import type { Profile } from '../types';

type ProfileCardProps = {
  profile: Profile;
};

// UI-027 계정 카드: 좌→우 그라디언트 2px 보더, 좌측 마스코트 아바타, 우측 닉네임·이메일.
export function ProfileCard({ profile }: ProfileCardProps) {
  return (
    <LinearGradient
      colors={['#D791FF', '#AE5DDD']}
      start={{ x: 0, y: 0 }}
      end={{ x: 1, y: 0 }}
      style={styles.borderWrapper}>
      <View style={styles.card}>
        <View style={styles.avatar}>
          <Image
            source={require('@/assets/brand/mascot-default.png')}
            style={styles.avatarImage}
            resizeMode="contain"
          />
        </View>
        <View style={styles.info}>
          <Text style={styles.name} numberOfLines={1}>
            {profile.nickname}
          </Text>
          <Text style={styles.email} numberOfLines={1}>
            {profile.email}
          </Text>
        </View>
      </View>
    </LinearGradient>
  );
}

const CARD_HEIGHT = 105;
const BORDER_WIDTH = 2;
const RADIUS = 17;
const AVATAR_SIZE = 67;
const AVATAR_IMAGE_WIDTH = AVATAR_SIZE - 14;
const AVATAR_IMAGE_HEIGHT = Math.round((AVATAR_IMAGE_WIDTH * 534) / 711);

const styles = StyleSheet.create({
  borderWrapper: {
    height: CARD_HEIGHT,
    borderRadius: RADIUS,
    padding: BORDER_WIDTH,
    marginHorizontal: 21,
    marginBottom: 12,
  },
  card: {
    flex: 1,
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#FFFFFF',
    borderRadius: RADIUS - BORDER_WIDTH,
    paddingHorizontal: 16,
  },
  avatar: {
    width: AVATAR_SIZE,
    height: AVATAR_SIZE,
    borderRadius: 16,
    backgroundColor: '#F0D5FF',
    alignItems: 'center',
    justifyContent: 'center',
    overflow: 'hidden',
  },
  avatarImage: {
    width: AVATAR_IMAGE_WIDTH,
    height: AVATAR_IMAGE_HEIGHT,
  },
  info: {
    marginLeft: 14,
    flexShrink: 1,
  },
  name: {
    fontSize: 16,
    fontWeight: '600',
    color: '#1D1D23',
  },
  email: {
    marginTop: 4,
    fontSize: 9,
    fontWeight: '400',
    color: '#85818A',
  },
});
