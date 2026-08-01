import type { SolarRequestItem } from '../types';

export type RequestItemCardDisplay = {
  badgeLabel: string;
  summaryText: string;
  isDelete: boolean;
};

export function getRequestItemCardDisplay(item: SolarRequestItem): RequestItemCardDisplay {
  if (item.action === 'DELETE') {
    return {
      badgeLabel: item.actionLabel,
      summaryText: '삭제 예정',
      isDelete: true,
    };
  }

  return {
    badgeLabel: item.entityLabel,
    summaryText: item.summaryText,
    isDelete: false,
  };
}
