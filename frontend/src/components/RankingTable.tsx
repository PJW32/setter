import { useState } from 'react'

import { FACTORS, fmt, rawText, violationText, won } from '../lib/format'
import type { DongCard, ResultPayload } from '../lib/types'

type Props = { result: ResultPayload; selected: string | null; onSelect: (c: string) => void }

export default function RankingTable({ result, selected, onSelect }: Props) {
  const [showAll, setShowAll] = useState(false)
  const rows = showAll ? result.ranked : result.ranked.slice(0, 15)
  const near = new Set(result.near_misses)

  return (
    <div className="ranking">
      <div className="legend" role="list" aria-label="요인 색과 현재 비중">
        {FACTORS.map((f) => (
          <span key={f.key} role="listitem" className="legend-item">
            <span className="swatch" style={{ background: f.color }} />
            {f.label} <span className="legend-w">{Math.round(result.weights[f.key] * 100)}%</span>
          </span>
        ))}
      </div>

      <table className="rank-table">
        <caption className="sr-only">조건을 만족한 동네 순위. 점수는 요인별 점수의 합입니다.</caption>
        <thead>
          <tr>
            <th scope="col">순위</th>
            <th scope="col">동네</th>
            <th scope="col" className="col-score">점수와 구성</th>
            <th scope="col" className="num">월 총비용</th>
            <th scope="col" className="num">통근</th>
            <th scope="col" className="num">역까지</th>
            <th scope="col">참고</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.dong_code} className={d.dong_code === selected ? 'is-selected' : ''}
              onClick={() => onSelect(d.dong_code)} tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter') onSelect(d.dong_code) }}>
              <td className="num rank-no">{d.rank}</td>
              <td><span className="dong-name">{d.name}</span><span className="dong-sgg">{d.sgg}</span></td>
              <td><ScoreBar d={d} /></td>
              <td className="num">{d.raw.monthly_cost == null ? '–' : won(d.raw.monthly_cost)}</td>
              <td className="num">{fmt(d.raw.commute, 0)}분</td>
              <td className="num">{rawText('station_access', d.raw.station_access).replace('도보 ', '')}</td>
              <td><Flags d={d} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      {result.ranked.length > 15 && (
        <button className="link-btn" onClick={() => setShowAll((v) => !v)}>
          {showAll ? '상위 15곳만 보기' : `나머지 ${result.ranked.length - 15}곳 더 보기`}
        </button>
      )}

      {result.excluded.length > 0 && (
        <details className="excluded" open={near.size > 0}>
          <summary>조건 밖이라 제외한 동네 {result.excluded.length}곳</summary>
          <ul>
            {result.excluded.slice(0, 30).map((d) => (
              <li key={d.dong_code} className={near.has(d.dong_code) ? 'is-near' : ''}>
                <button className="link-btn" onClick={() => onSelect(d.dong_code)}>{d.sgg} {d.name}</button>
                {' '}{d.violations?.map((v, i) => <span key={i} className="why">{violationText(v)}</span>)}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export function ScoreBar({ d }: { d: DongCard }) {
  return (
    <div className="scorebar">
      <span className="score-num">{fmt(d.score)}</span>
      <span className="bar" role="img"
        aria-label={FACTORS.map((f) => `${f.label} ${fmt(d.contrib[f.key])}점`).join(', ')}>
        {FACTORS.map((f) => (
          <span key={f.key} className="seg" title={`${f.label} ${fmt(d.contrib[f.key])}점 · ${rawText(f.key, d.raw[f.key])}`}
            style={{ width: `${d.contrib[f.key]}%`, background: f.color }} />
        ))}
      </span>
    </div>
  )
}

export function Flags({ d }: { d: DongCard }) {
  return (
    <span className="flags">
      {d.flags.map((f) => (
        <span key={f} className={f.includes('부족') || f.includes('불가') ? 'flag flag-warn' : 'flag'}>{f}</span>
      ))}
    </span>
  )
}
