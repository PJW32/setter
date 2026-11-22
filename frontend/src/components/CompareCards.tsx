import { useState, type ReactNode } from 'react'

import { FACTORS, fmt, violationText, won } from '../lib/format'
import type { DongCard, ResultPayload } from '../lib/types'
import { Flags, ScoreBar } from './RankingTable'

type Props = { result: ResultPayload; selected: string | null; conversionRate: number; focus?: string[] }

const MAX_COLS = 3

/** 후보 비교: 동네를 열로, 항목을 행으로 놓은 한 장의 표.
 *  기본은 상위 3곳 (고른 동이 3위 밖이면 마지막 칸), 대화에서 두 곳 이상을 비교하면(focus) 그 동네들.
 *  행마다 가장 나은 값에 '유리' 표시를 하고, 나머지 칸에는 그 값과의 차이를 적는다. */
export default function CompareCards({ result, selected, conversionRate, focus = [] }: Props) {
  const all = [...result.ranked, ...result.excluded]
  const byCode = new Map(all.map((d) => [d.dong_code, d]))
  const top = result.ranked.slice(0, MAX_COLS)
  const focused = focus.map((c) => byCode.get(c)).filter((d): d is DongCard => !!d)
  const sel = selected ? byCode.get(selected) : undefined
  const defaults = focused.length >= 2 ? focused.slice(0, MAX_COLS)
    : sel && !top.some((d) => d.dong_code === sel.dong_code) ? [...top.slice(0, MAX_COLS - 1), sel] : top
  // 사용자가 칸을 바꾸면 그 선택을 쓰되, 기본 목록(결과·대화·선택)이 바뀌면 다시 기본으로
  const base = defaults.map((d) => d.dong_code).join(',') + '|' + result.ranked.length
  const [picked, setPicked] = useState<{ base: string; codes: string[] } | null>(null)
  const codes = picked?.base === base ? picked.codes : defaults.map((d) => d.dong_code)
  const cols = codes.map((c) => byCode.get(c)).filter((d): d is DongCard => !!d)

  if (!cols.length) return <p className="panel-empty">조건을 만족하는 동네가 없어요. 조건을 조금 풀어 보세요.</p>

  const setCodes = (next: string[]) => setPicked({ base, codes: next })
  const replace = (i: number, code: string) => setCodes(codes.map((c, j) => (j === i ? code : c)))
  const remove = (i: number) => setCodes(codes.filter((_, j) => j !== i))
  const add = () => {
    const next = result.ranked.find((d) => !codes.includes(d.dong_code))
    if (next) setCodes([...codes, next.dong_code])
  }

  const convKeys = [...new Set(cols.flatMap((d) => Object.keys(d.convenience)))]
  const depositMonthly = (d: DongCard) => d.cost.median_deposit != null ? (d.cost.median_deposit * conversionRate) / 12 : null

  return (
    <div className="cmp">
      <Winners cols={cols} />

      <div className="cmp-scroll" role="region" aria-label="후보 동네 비교표" tabIndex={0}>
        <table className="cmp-table" style={{ ['--cols' as string]: cols.length }}>
          <caption className="sr-only">후보 동네를 항목별로 비교한 표. 유리 표시는 그 항목에서 가장 나은 동네</caption>
          <thead>
            <tr>
              <th scope="col" className="cmp-corner">
                {cols.length < MAX_COLS && result.ranked.length > cols.length && (
                  <button type="button" className="btn-ghost cmp-add" onClick={add}>＋ 동네 추가</button>
                )}
              </th>
              {cols.map((d, i) => (
                <th key={d.dong_code} scope="col" className="cmp-head">
                  <div className="cmp-head-top">
                    <label className="cmp-pick" title="눌러서 다른 동네로 바꾸기">
                      <select value={d.dong_code} aria-label={`${i + 1}번째 칸 동네 (바꾸려면 선택)`} onChange={(e) => replace(i, e.target.value)}>
                        <optgroup label="추천 동네">
                          {result.ranked.map((o) => (
                            <option key={o.dong_code} value={o.dong_code} disabled={o.dong_code !== d.dong_code && codes.includes(o.dong_code)}>
                              {o.rank}위 {o.name}
                            </option>
                          ))}
                        </optgroup>
                        {result.excluded.length > 0 && (
                          <optgroup label="조건 밖">
                            {result.excluded.map((o) => (
                              <option key={o.dong_code} value={o.dong_code} disabled={o.dong_code !== d.dong_code && codes.includes(o.dong_code)}>
                                조건 밖 · {o.name}
                              </option>
                            ))}
                          </optgroup>
                        )}
                      </select>
                    </label>
                    {cols.length > 2 && (
                      <button type="button" className="cmp-x" aria-label={`${d.name} 비교에서 빼기`} title="비교에서 빼기" onClick={() => remove(i)}>×</button>
                    )}
                  </div>
                  <span className="dong-sgg">{d.sgg}</span>
                </th>
              ))}
            </tr>
          </thead>

          <tbody>
            <Group title="점수" n={cols.length} />
            <Row label="종합 점수" cols={cols} get={(d) => d.score} better="high" unit="점" strong
              render={(d) => <ScoreBar d={d} />} />
            {FACTORS.map((f) => (
              <Row key={f.key} label={<><span className="swatch" style={{ background: f.color }} />{f.label}</>}
                cols={cols} get={(d) => d.contrib[f.key]} better="high" unit="점"
                render={(d) => (
                  <span className="cmp-meter" title={`${f.label}에서 후보 중 위치 ${Math.round(d.norm[f.key] * 100)}%`}>
                    <span className="cmp-meter-fill" style={{ width: `${Math.max(0, Math.min(1, d.norm[f.key])) * 100}%`, background: f.color }} />
                  </span>
                )} />
            ))}

            <Group title="돈" n={cols.length} />
            <Row label="월 총비용" cols={cols} get={(d) => d.cost.monthly_total} better="low" unit="만원" strong />
            <Row label="월세 중앙값" cols={cols} get={(d) => d.cost.median_rent} better="low" unit="만원" />
            <Row label="보증금 중앙값" cols={cols} get={(d) => d.cost.median_deposit} better="low" unit="만원"
              render={(d) => depositMonthly(d) != null && <small className="cmp-sub">월 약 {fmt(depositMonthly(d))}만 원으로 환산</small>} />
            <Row label="월 교통비" cols={cols} get={(d) => d.cost.fare_month} better="low" unit="만원" />
            <Row label="실거래 표본" cols={cols} get={(d) => d.cost.samples} unit="건" digits={0} />

            <Group title="통근" n={cols.length} />
            <Row label="통근 시간" cols={cols} get={(d) => d.commute.min ?? null} better="low" unit="분" digits={0} strong
              render={(d) => d.commute.map_url && <a className="cmp-sub" href={d.commute.map_url} target="_blank" rel="noreferrer">경로 보기</a>} />
            <Row label="환승" cols={cols} get={(d) => d.commute.min == null ? null : d.commute.transfers ?? 0} better="low" unit="회" digits={0} />
            <TextRow label="이용 노선" cols={cols} text={(d) => [d.commute.mode, ...(d.commute.lines ?? [])].filter(Boolean).join(' · ') || '–'} />

            <Group title="생활" n={cols.length} />
            <TextRow label="가까운 역" cols={cols} text={(d) => d.station.name ?? '3km 안에 없음'} />
            <Row label="역까지 도보" cols={cols} get={(d) => d.station.walk_min ?? d.raw.station_access} better="low" unit="분" digits={0} />
            <Row label="생활 편의 점수" cols={cols} get={(d) => d.raw.convenience} better="high" unit="점" />
            {convKeys.map((k) => (
              <Row key={k} label={k} cols={cols} get={(d) => d.convenience[k] ?? null} better="high" unit="곳" digits={0} />
            ))}
            <Row label="주변 주점 (500m)" cols={cols} get={(d) => d.bars.count ?? null} better="low" unit="곳" digits={0} />

            {cols.some((d) => d.flags.length || d.violations?.length) && (
              <>
                <Group title="참고" n={cols.length} />
                <tr>
                  <th scope="row">데이터·조건</th>
                  {cols.map((d) => (
                    <td key={d.dong_code}>
                      <Flags d={d} />
                      {d.violations?.map((v, i) => <p key={i} className="cmp-why">{violationText(v)}</p>)}
                    </td>
                  ))}
                </tr>
              </>
            )}
          </tbody>

          <tfoot>
            <tr>
              <th scope="row">매물 찾아보기</th>
              {cols.map((d) => (
                <td key={d.dong_code} className="cmp-links">
                  <a href={`https://map.kakao.com/?q=${encodeURIComponent(`${d.sgg} ${d.name}`)}`} target="_blank" rel="noreferrer">카카오맵</a>
                  <a href="https://www.zigbang.com/" target="_blank" rel="noreferrer">직방</a>
                  <a href="https://www.dabangapp.com/" target="_blank" rel="noreferrer">다방</a>
                </td>
              ))}
            </tr>
          </tfoot>
        </table>
      </div>

      <p className="fine">
        <span className="cmp-best-key">유리</span> 표시는 그 항목에서 가장 나은 동네이고, 다른 칸의 회색 숫자는 그 동네와의 차이예요.
        요인 점수 막대는 후보 전체 중 위치(오른쪽일수록 좋음)예요.
        월세·보증금·교통비는 항목마다 중앙값이라 합이 월 총비용과 꼭 같지는 않고, 관리비는 포함되지 않아요.
        역까지 도보는 직선거리로 추정했고, 조용함은 주변 주점 수로 추정하며 실제 소음이나 밤길 안전을 뜻하지 않아요.
      </p>
    </div>
  )
}

/** 요인마다 어느 동네가 가장 나은지 한 줄로 */
function Winners({ cols }: { cols: DongCard[] }) {
  if (cols.length < 2) return null
  const items = FACTORS.map((f) => {
    const vals = cols.map((d) => d.contrib[f.key])
    const best = Math.max(...vals)
    const winners = cols.filter((_, i) => vals[i] === best)
    return { f, name: winners.length === cols.length ? '비슷함' : winners.map((d) => d.name).join(', ') }
  })
  const scoreBest = cols.reduce((a, b) => (b.score > a.score ? b : a))
  return (
    <section className="cmp-winners" aria-label="요인별로 더 나은 동네">
      <p className="cmp-verdict">
        종합 점수는 <strong>{scoreBest.name}</strong>이 가장 높아요 ({fmt(scoreBest.score)}점).
      </p>
      <ul>
        {items.map(({ f, name }) => (
          <li key={f.key}>
            <span className="swatch" style={{ background: f.color }} />
            <span className="cmp-w-label">{f.label}</span>
            <strong>{name}</strong>
          </li>
        ))}
      </ul>
    </section>
  )
}

function Group({ title, n }: { title: string; n: number }) {
  return (
    <tr className="cmp-group">
      <th scope="rowgroup" colSpan={n + 1}>{title}</th>
    </tr>
  )
}

type RowProps = {
  label: ReactNode; cols: DongCard[]; get: (d: DongCard) => number | null | undefined
  better?: 'low' | 'high'; unit: '점' | '만원' | '분' | '곳' | '건' | '회'; digits?: number; strong?: boolean
  render?: (d: DongCard) => ReactNode
}

/** 숫자 행: 가장 나은 값에 '유리', 나머지는 그 값과의 차이 */
function Row({ label, cols, get, better, unit, digits = 1, strong, render }: RowProps) {
  const vals = cols.map((d) => {
    const v = get(d)
    return v == null || !Number.isFinite(v) ? null : v
  })
  const present = vals.filter((v): v is number => v != null)
  const best = better && present.length >= 2
    ? (better === 'low' ? Math.min(...present) : Math.max(...present)) : null
  const allSame = best != null && present.every((v) => v === best)
  const show = (v: number) => (unit === '만원' ? won(v) : `${fmt(v, digits)}${unit}`)
  // 가장 나은 값과의 차이 (부호 포함): +3.1만 원, −3.7점
  const gap = (v: number) => {
    const d = v - (best as number)
    const sign = d > 0 ? '+' : '−'
    return `${sign}${unit === '만원' ? `${fmt(Math.abs(d))}만 원` : `${fmt(Math.abs(d), digits)}${unit}`}`
  }

  return (
    <tr className={strong ? 'cmp-strong' : undefined}>
      <th scope="row">{label}</th>
      {cols.map((d, i) => {
        const v = vals[i]
        const isBest = best != null && !allSame && v === best
        return (
          <td key={d.dong_code} className={isBest ? 'is-best' : undefined}>
            <span className="cmp-val">
              <span className="num">{v == null ? '데이터 없음' : show(v)}</span>
              {isBest && <span className="cmp-best-key">유리</span>}
              {best != null && !allSame && v != null && v !== best && (
                <span className="cmp-gap">{gap(v)}</span>
              )}
            </span>
            {render?.(d)}
          </td>
        )
      })}
    </tr>
  )
}

function TextRow({ label, cols, text }: { label: string; cols: DongCard[]; text: (d: DongCard) => string }) {
  return (
    <tr>
      <th scope="row">{label}</th>
      {cols.map((d) => <td key={d.dong_code} className="cmp-text">{text(d)}</td>)}
    </tr>
  )
}
