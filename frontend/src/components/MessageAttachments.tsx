import { fmt, won } from '../lib/format'
import type { Attachment, AttachmentRow, CompareItem } from '../lib/types'

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
  title: string; rows: AttachmentRow[]; compare?: { a: string; b: string; items: CompareItem[] }
  onFocusDong: (code: string) => void
}) {
  return (
    <section className="att" aria-label={title}>
      <h3>{title}</h3>
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

function CompareTable({ compare }: { compare: { a: string; b: string; items: CompareItem[] } }) {
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
