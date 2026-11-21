import type { LogEvent, LogStep } from '../lib/types'

const STEP_NAME: Record<LogStep, string> = {
  extract: '조건 해석',
  destination: '목적지 찾기',
  region: '후보 지역',
  collect: '지역 데이터 수집',
  commute: '통근 계산',
  dataset: '후보 동 준비',
  score: '점수 계산',
  tradeoff: '상충 확인',
  explain: '설명 작성',
}
const ORDER: LogStep[] = ['extract', 'destination', 'region', 'collect', 'commute', 'dataset', 'score', 'tradeoff', 'explain']

/** 에이전트 작업 로그를 노선도처럼: 단계 = 역, 진행 중인 역에 열차 점 */
export default function AgentLine({ logs, busy }: { logs: LogEvent[]; busy: boolean }) {
  const byStep = new Map<LogStep, LogEvent[]>()
  for (const l of logs) byStep.set(l.step, [...(byStep.get(l.step) ?? []), l])
  const steps = ORDER.filter((s) => byStep.has(s))

  return (
    <section className="panel line-panel" aria-label="에이전트 작업 로그">
      <h2 className="panel-title">에이전트가 한 일</h2>
      {steps.length === 0 ? (
        <p className="panel-empty">말을 보내면 조건 해석부터 설명까지 진행 과정이 여기 표시돼요.</p>
      ) : (
        <ol className="line">
          {steps.map((s) => {
            const evs = byStep.get(s)!
            const last = evs[evs.length - 1]
            const status = busy || last.status !== 'running' ? last.status : 'done'
            const subs = s === 'collect' ? evs.filter((e) => e.status !== 'running') : []
            const ms = evs.find((e) => e.ms)?.ms
            return (
              <li key={s} className={`stop stop-${status}`}>
                <span className="stop-dot" aria-hidden="true" />
                <div className="stop-body">
                  <span className="stop-name">
                    {STEP_NAME[s]}
                    <span className="sr-only"> ({statusText(status)})</span>
                    {ms != null && <span className="stop-ms">{(ms / 1000).toFixed(1)}초</span>}
                  </span>
                  <span className="stop-detail">{last.detail}</span>
                  {subs.length > 0 && (
                    <ul className="stop-subs">
                      {subs.map((e, i) => <li key={i} className={`sub-${e.status}`}>{e.detail}</li>)}
                    </ul>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      )}
      {busy && logs.some((l) => l.step === 'collect' && l.status === 'running') && (
        <p className="line-note">처음 보는 지역이라 공공데이터를 모으는 중이에요. 몇 분 걸릴 수 있어요.</p>
      )}
    </section>
  )
}

function statusText(s: string) {
  return s === 'running' ? '진행 중' : s === 'done' ? '완료' : s === 'warn' ? '주의' : '실패'
}
