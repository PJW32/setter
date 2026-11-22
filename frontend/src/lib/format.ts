import type { ConstraintKey, FactorKey, Level, Violation } from './types'

type Factor = { key: FactorKey; label: string; short: string; color: string }
export const FACTORS: Factor[] = [
  { key: 'monthly_cost', label: '월 총비용', short: '비용', color: '#5578ce' },
  { key: 'commute', label: '통근 시간', short: '통근', color: '#d86d43' },
  { key: 'station_access', label: '역 접근성', short: '역', color: '#60ac80' },
  { key: 'convenience', label: '생활 편의', short: '편의', color: '#dca630' },
  { key: 'quiet', label: '조용함', short: '조용', color: '#ce7fa3' },
]
export const FACTOR = Object.fromEntries(FACTORS.map((f) => [f.key, f])) as Record<FactorKey, Factor>
export const FACTOR_BY_LABEL: Record<string, Factor> = Object.fromEntries(FACTORS.map((f) => [f.label, f]))
export const LEVEL_VALUE: Record<Level, number> = { '매우 중요': 4, '중요': 3, '보통': 2, '조금': 1, '상관없음': 0 }
export const CONSTRAINT_LABEL: Record<ConstraintKey, string> = {
  max_deposit: '보증금', max_monthly_rent: '월세', max_commute_min: '통근', max_monthly_cost: '월 총비용',
}

export function fmt(value: number | null | undefined, digits = 1): string {
  return value == null || !Number.isFinite(value) ? '–' : value.toLocaleString('ko-KR', { maximumFractionDigits: digits })
}
/** 서버 금액 단위는 만원이며 교통요금(fare)만 원이다. */
export function won(value: number | null | undefined): string {
  return value == null ? '데이터 없음' : `${fmt(value)}만 원`
}
export function constraintText(key: ConstraintKey, value: number): string {
  return `${CONSTRAINT_LABEL[key]} ${key === 'max_commute_min' ? `${fmt(value)}분` : won(value)} 이하`
}
export function rawText(key: FactorKey, value: number | null | undefined): string {
  if (value == null) return '데이터 없음'
  switch (key) {
    case 'monthly_cost': return won(value)
    case 'commute': return `${fmt(value)}분`
    case 'station_access': return `도보 ${fmt(value)}분`
    case 'convenience': return `${fmt(value)}점`
    case 'quiet': return `${fmt(value, 0)}곳`
  }
}
export function violationText(v: Violation): string {
  const reason = { budget: '예산 조건 밖', commute: '통근 한도 초과', monthly_cost: '월 총비용 한도 초과' }[v.constraint]
  const relax = (Object.entries(v.relax_to) as [ConstraintKey, number][]).map(([k, n]) => constraintText(k, n))
  return relax.length ? `${reason} · ${relax.join(', ')}로 완화하면 포함` : reason
}
export const MAP_SCORE_COLORS = ['#e9deff', '#35205f'] as const

export function scoreColor(score: number, low: number, high: number): string {
  const ratio = high > low ? Math.max(0, Math.min(1, (score - low) / (high - low))) : 0.5
  return `color-mix(in srgb, ${MAP_SCORE_COLORS[0]}, ${MAP_SCORE_COLORS[1]} ${ratio * 100}%)`
}
