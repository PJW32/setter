import { fmt, won } from '../lib/format'
import type { Attachment, AttachmentRow, CompareData, FactorPoint } from '../lib/types'

/** 답변 아래에 붙는 자료: 동네 요약 표(두 곳이면 차이 포함), 직접 확인하는 방법 */
export default function MessageAttachments({ items, onFocusDong }: {
  items: Attachment[]; onFocusDong: (code: string) => void
}) {
  return (
    <div className="msg-atts">
      {items.map((a, i) => a.kind === 'dongs'
        ? <DongTable key={i} title={a.title} rows={a.rows} compare={a.compare} onFocusDong={onFocusDong} />
        : (
          <section key={i} className="att att-guides" aria-label={a.title}>
            <h3>{a.title}</h3>
            <ul>
              {a.items.map((g) => (
                <li key={g.topic}>
                  <strong>{g.topic}</strong> {g.how}
                  {g.links.length > 0 && (
                    <span className="att-links">
                      {g.links.map((l) => <a key={l.url} href={l.url} target="_blank" rel="noreferrer">{l.label}</a>)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>
        ))}
    </div>
  )
}

function DongTable({ title, rows, compare, onFocusDong }: {
  title: string; rows: AttachmentRow[]; compare?: CompareData
  onFocusDong: (code: string) => void
}) {
  return (
    <section className="att" aria-label={title}>
      <h3>{title}</h3>
      {compare?.factors && <FactorBars a={compare.a} b={compare.b} factors={compare.factors} />}
      {compare ? <CompareTable compare={compare} /> : (
        <table className="att-table">
          <thead>
            <tr><th scope="col">동네</th><th scope="col" className="num">월 총비용</th><th scope="col" className="num">통근</th><th scope="col" className="num">역까지</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.dong_code}>
                <th scope="row">
                  <span className={r.excluded ? 'att-status att-out' : 'att-status'}>{r.status}</span>
                  {r.name}
                  {r.reason && <span className="att-reason">{r.reason}</span>}
                </th>
                <td className="num">{won(r.monthly_cost)}</td>
                <td className="num">{r.commute == null ? '–' : `${fmt(r.commute, 0)}분`}</td>
                <td className="num">{r.station_walk == null ? '–' : `${fmt(r.station_walk, 0)}분`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="att-actions">
        {rows.map((r) => (
          <button key={r.dong_code} type="button" className="link-btn" onClick={() => onFocusDong(r.dong_code)}>
            {r.name} 지도에서 보기
          </button>
        ))}
      </div>
    </section>
  )
}

/** 두 동네의 요인별 점수를 나란히 막대로. 점수 = 요인별 점수의 합 */
function FactorBars({ a, b, factors }: { a: string; b: string; factors: FactorPoint[] }) {
  const max = Math.max(1, ...factors.flatMap((f) => [f.a, f.b]))
  return (
    <figure className="fbars" aria-label={`${a}와 ${b}의 요인별 점수`}>
      <figcaption className="fbars-legend">
        <span><i className="fbars-key fbars-a" />{a}</span>
        <span><i className="fbars-key fbars-b" />{b}</span>
        <span className="fbars-note">요인별 점수 (합 = 총점)</span>
      </figcaption>
      {factors.map((f) => (
        <div key={f.key} className="fbars-row">
          <span className="fbars-label">{f.label}</span>
          <span className="fbars-pair">
            <span className="fbars-line">
              <span className="fbars-bar fbars-a" style={{ width: `${(f.a / max) * 100}%` }} />
              <span className="fbars-val">{fmt(f.a)}</span>
            </span>
            <span className="fbars-line">
              <span className="fbars-bar fbars-b" style={{ width: `${(f.b / max) * 100}%` }} />
              <span className="fbars-val">{fmt(f.b)}</span>
            </span>
          </span>
        </div>
      ))}
    </figure>
  )
}

function CompareTable({ compare }: { compare: CompareData }) {
  const shown = compare.items.filter((i) => i.a != null || i.b != null)
  return (
    <table className="att-table">
      <thead>
        <tr><th scope="col">항목</th><th scope="col" className="num">{compare.a}</th><th scope="col" className="num">{compare.b}</th><th scope="col">유리한 쪽</th></tr>
      </thead>
      <tbody>
        {shown.map((i) => (
          <tr key={i.label}>
            <th scope="row">{i.label}</th>
            <td className="num">{val(i.a, i.unit)}</td>
            <td className="num">{val(i.b, i.unit)}</td>
            <td className="att-diff">
              {i.abs_diff ? <><strong>{i.better}</strong> {val(i.abs_diff, i.unit)}</> : i.diff === 0 ? '같음' : '–'}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function val(v: number | null, unit: string) {
  if (v == null) return '–'
  return unit === '만원' ? won(v) : `${fmt(v)}${unit}`
}
