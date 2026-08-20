export const SUPPORTED_LOCALES = new Set(['ko', 'en', 'ja', 'zh-CN']);

export function normalizeLocale(value) {
  if (value === undefined || value === null || value === '') return 'ko';
  return SUPPORTED_LOCALES.has(value) ? value : null;
}
