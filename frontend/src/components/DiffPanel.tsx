import { FACTOR_BY_LABEL, fmt } from '../lib/format'
import type { Diff } from '../lib/types'

/** 순위가 바뀐 이유: 추월한 두 동의 점수 격차가 요인별로 몇 점 움직였는지 */
export default function DiffPanel({ diff }: { diff: Diff | null }) {
  const moves = diff?.moves.filter((m) => m.cur_rank != null && m.cur_rank <= 10).slice(0, 6) ?? []
  const ot = diff?.overtakes[0]
  const max = ot ? Math.max(1, ...Object.values(ot.by_factor).map(Math.abs)) : 1

  return (
    <section className="panel diff-panel" aria-label="순위 변동">
      <h2 className="panel-title">순위가 바뀐 이유</h2>
      {!diff || (!moves.length && !ot) ? (
        <p className="panel-empty">조건을 바꾸면, 어떤 동네가 왜 오르내렸는지 여기서 보여드려요.</p>
      ) : (
        <>
          {Object.keys(diff.weight_change).length > 0 && (
            <p className="diff-weights">
              비중 변화: {Object.entries(diff.weight_change).map(([k, v]) => `${k} ${v > 0 ? '+' : ''}${Math.round(v * 100)}%p`).join(', ')}
            </p>
          )}
          <ul className="moves">
            {moves.map((m) => {
              const up = m.change != null && m.change > 0
              return (
                <li key={m.dong_code}>
                  <span className={up ? 'mv mv-up' : 'mv mv-down'} aria-hidden="true">{up ? '▲' : '▼'}</span>
                  {m.name} <span className="mv-ranks">{m.prev_rank ?? '–'}위 → {m.cur_rank}위</span>
                </li>
              )
            })}
          </ul>
          {ot && (
            <figure className="overtake">
              <figcaption>
                <strong>{ot.a.name}</strong>이(가) <strong>{ot.b.name}</strong>을(를) 앞질렀어요.
                점수 차 {fmt(ot.gap_before)} → {fmt(ot.gap_after)}점
              </figcaption>
              <ul className="ot-bars">
                {Object.entries(ot.by_factor).map(([label, v]) => {
                  const f = FACTOR_BY_LABEL[label]
                  const w = (Math.abs(v) / max) * 50
                  return (
                    <li key={label}>
                      <span className="ot-label">{label}</span>
                      <span className="ot-track">
                        <span className="ot-axis" />
                        <span className="ot-fill" style={{
                          background: f?.color, width: `${w}%`,
                          left: v >= 0 ? '50%' : `${50 - w}%`,
                        }} />
                      </span>
                      <span className="ot-val num">{v > 0 ? '+' : ''}{fmt(v, 2)}</span>
                    </li>
                  )
                })}
              </ul>
              <p className="fine">오른쪽(+)은 {ot.a.name}에 유리하게 움직인 만큼, 왼쪽(−)은 불리하게 움직인 만큼이에요.</p>
            </figure>
          )}
        </>
      )}
    </section>
  )
}
