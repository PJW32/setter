import { CONSTRAINT_LABEL, FACTORS, LEVEL_VALUE, constraintText } from '../lib/format'
import type { ConstraintKey, StateSnapshot } from '../lib/types'

/** 상단: 서비스 이름 + 목적지를 역 표지판처럼 + 현재 조건 */
export default function StationSign({ state, busy, onReset }: { state: StateSnapshot | null; busy: boolean; onReset: () => void }) {
  const dest = state?.destination
  const cons = Object.entries(state?.constraints ?? {}) as [ConstraintKey, number][]
  return (
    <header className="sign">
      <div className="brand">
        <img className="brand-mark" src="/setter-icon-192.png" width="42" height="42" alt="" />
        <span className="brand-name">새터 <span lang="en">setter</span></span>
      </div>

      <div className="sign-plate" aria-label="목적지">
        {dest ? (
          <>
            <span className="sign-to">도착</span>
            <span className="sign-station">{dest.key}</span>
            {dest.station_lines.length > 0 && (
              <span className="sign-lines">{dest.station_lines.slice(0, 3).join(' · ')}</span>
            )}
            {dest.walk_from_station_min > 0 && (
              <span className="sign-walk">{dest.place_name}까지 도보 {dest.walk_from_station_min}분</span>
            )}
          </>
        ) : (
          <span className="sign-empty">목적지를 말해 주세요</span>
        )}
      </div>

      <div className="conditions" aria-label="현재 조건">
        {cons.map(([k, v]) => (
          <span key={k} className="chip chip-hard" title={`필수 조건: ${CONSTRAINT_LABEL[k]}`}>{constraintText(k, v)}</span>
        ))}
        {state && FACTORS.map((f) => {
          const lv = state.levels[f.key]
          const n = LEVEL_VALUE[lv]
          return (
            <span key={f.key} className="chip chip-pref" title={`${f.label}: ${lv}`}>
              <span className="pref-dot" style={{ background: f.color }} aria-hidden="true" />
              {f.short}
              <span className="pref-meter" aria-label={lv}>
                {[1, 2, 3, 4].map((i) => <i key={i} className={i <= n ? 'on' : ''} />)}
              </span>
            </span>
          )
        })}
      </div>

      <button className="btn-ghost" onClick={onReset} disabled={busy}>새 대화</button>
    </header>
  )
}
