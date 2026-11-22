import { useState } from 'react'

import { FACTORS, fmt, rawText, violationText } from '../lib/format'
import type { DongCard, FactorKey, ResultPayload } from '../lib/types'

type Sort = 'rank' | FactorKey
type Props = { result: ResultPayload; onCompare: (code: string) => void }

export default function RankingTable({ result, onCompare }: Props) {
  const [showAll, setShowAll] = useState(false)
  const [query, setQuery] = useState('')
  const [sort, setSort] = useState<Sort>('rank')
  const normalized = query.trim().normalize('NFC').toLowerCase()
  const matching = result.ranked.filter((d) =>
    `${d.sido} ${d.sgg} ${d.name}`.normalize('NFC').toLowerCase().includes(normalized),
  )
  if (sort !== 'rank') {
    matching.sort((a, b) => {
      const left = a.raw[sort]
      const right = b.raw[sort]
      if (left == null) return right == null ? 0 : 1
      if (right == null) return -1
      return sort === 'convenience' ? right - left : left - right
    })
  }
  const rows = showAll ? matching : matching.slice(0, 15)
  const near = new Set(result.near_misses)

  return (
    <div className="ranking">
      <div className="ranking-filters">
        <label>동네 이름
          <input type="search" value={query} onChange={(e) => {
            setQuery(e.target.value)
            setShowAll(false)
          }} placeholder="예: 성수동" />
        </label>
        <label>정렬 기준
          <select value={sort} onChange={(e) => {
            setSort(e.target.value as Sort)
            setShowAll(false)
          }}>
            <option value="rank">추천 순위</option>
            {FACTORS.map((f) => (
              <option key={f.key} value={f.key}>{f.key === 'quiet' ? '주점 수' : f.label} {f.key === 'convenience' ? '높은 순' : '낮은 순'}</option>
            ))}
          </select>
        </label>
      </div>
      {!!normalized && <p className="fine" role="status">검색 결과 {matching.length}곳</p>}
      <div className="legend" role="list" aria-label="요인 색과 현재 비중">
        {FACTORS.map((f) => (
          <span key={f.key} role="listitem" className="legend-item">
            <span className="swatch" style={{ background: f.color }} />
            {f.label} <span className="legend-w">{Math.round(result.weights[f.key] * 100)}%</span>
          </span>
        ))}
      </div>

      {rows.length > 0 ? <div className="rank-table-scroll" role="region" aria-label="동네 순위표" tabIndex={0}>
      <table className="rank-table">
        <caption className="sr-only">동네 순위와 다섯 가지 비교 기준</caption>
        <thead>
          <tr>
            <th scope="col">순위</th>
            <th scope="col">동네</th>
            <th scope="col" className="col-score">점수와 구성</th>
            {FACTORS.map((f) => {
              const label = f.key === 'quiet' ? '주점 수' : f.label
              return <th key={f.key} scope="col" className="num" title={label}>{label}</th>
            })}
            <th scope="col">비교</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((d) => (
            <tr key={d.dong_code}>
              <td className="num rank-no">{d.rank}</td>
              <td title={[d.name, d.sgg, ...d.flags].join(' · ')}><span className="dong-name">{d.name}</span><span className="dong-sgg">{d.sgg}</span><Flags d={d} /></td>
              <td><ScoreBar d={d} /></td>
              {FACTORS.map((f) => {
                const value = rawText(f.key, d.raw[f.key])
                return <td key={f.key} className="num" title={value}>{value}</td>
              })}
              <td><button type="button" className="link-btn" aria-label={`${d.sgg} ${d.name} 비교`} onClick={() => onCompare(d.dong_code)}>비교</button></td>
            </tr>
          ))}
        </tbody>
      </table>
      </div> : <p className="panel-empty">{normalized ? '이름이 일치하는 추천 동네가 없어요.' : '표시할 추천 동네가 없어요.'}</p>}
      {matching.length > 15 && (
        <button className="link-btn" onClick={() => setShowAll((v) => !v)}>
          {showAll ? '처음 15곳만 보기' : `나머지 ${matching.length - 15}곳 더 보기`}
        </button>
      )}

      {result.excluded.length > 0 && (
        <details className="excluded" open={near.size > 0}>
          <summary>조건 밖이라 제외한 동네 {result.excluded.length}곳</summary>
          <ul>
            {result.excluded.slice(0, 30).map((d) => (
              <li key={d.dong_code} className={near.has(d.dong_code) ? 'is-near' : ''}>
                <button type="button" className="link-btn" onClick={() => onCompare(d.dong_code)}>{d.sgg} {d.name} 비교</button>
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
