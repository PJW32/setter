import { useCallback, useEffect, useRef, useState } from 'react'

import AgentLine from './components/AgentLine'
import Chat, { type ChatItem } from './components/Chat'
import CompareCards from './components/CompareCards'
import DiffPanel from './components/DiffPanel'
import MapView from './components/MapView'
import RankingTable from './components/RankingTable'
import StationSign from './components/StationSign'
import TradeoffChart from './components/TradeoffChart'
import { createSession, restoreSession, sendMessage } from './lib/api'
import { FACTORS, rawText } from './lib/format'
import type { AgentEvent, LogEvent, ResultPayload, StateSnapshot } from './lib/types'

type Tab = 'map' | 'table' | 'tradeoff' | 'compare'
const TABS: { key: Tab; label: string }[] = [
  { key: 'map', label: '지도' },
  { key: 'table', label: '순위표' },
  { key: 'tradeoff', label: '비용·통근' },
  { key: 'compare', label: '후보 비교' },
]

export default function App() {
  const [sessionId, setSessionId] = useState<string | null>(null)
  const [items, setItems] = useState<ChatItem[]>([])
  const [state, setState] = useState<StateSnapshot | null>(null)
  const [result, setResult] = useState<ResultPayload | null>(null)
  const [hypo, setHypo] = useState<ResultPayload | null>(null) // 가정 질문 결과
  const [logs, setLogs] = useState<LogEvent[]>([])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('map')
  const [selected, setSelected] = useState<string | null>(null)
  const [mobileView, setMobileView] = useState<'chat' | 'results'>('chat')
  const idRef = useRef(0)

  const load = useCallback(async (fresh: boolean) => {
    try {
      const s = fresh ? await createSession() : await restoreSession()
      setSessionId(s.session_id)
      setState(s.state)
      setResult(s.result)
      setHypo(null)
      setLogs([])
      setSelected(null)
      setMobileView(s.result ? 'results' : 'chat')
      setItems(s.messages.map((m) => ({ id: ++idRef.current, kind: m.role, text: m.text, source: m.source, attachments: m.attachments })))
      setError(null)
    } catch (e) {
      setError(`서버에 연결하지 못했어요. 백엔드가 켜져 있는지 확인해 주세요. (${(e as Error).message})`)
    }
  }, [])

  useEffect(() => { load(false) }, [load])

  const onEvent = useCallback((ev: AgentEvent) => {
    switch (ev.type) {
      case 'log':
        setLogs((l) => [...l, ev])
        break
      case 'interpretation':
        setItems((it) => [...it, { id: ++idRef.current, kind: 'interpretation', interp: ev }])
        if (!ev.what_if) setState(ev.state)
        break
      case 'result':
        setMobileView('results')
        if (ev.what_if) {
          setHypo(ev.payload)
        } else {
          setResult(ev.payload)
          setHypo(null)
        }
        break
      case 'message':
        setItems((it) => [...it, { id: ++idRef.current, kind: 'assistant', text: ev.text, source: ev.source, attachments: ev.attachments }])
        break
      case 'error':
        setItems((it) => [...it, { id: ++idRef.current, kind: 'error', text: ev.detail }])
        break
    }
  }, [])

  const send = useCallback(async (text: string) => {
    if (!sessionId || busy) return
    setBusy(true)
    setLogs([])
    setItems((it) => [...it, { id: ++idRef.current, kind: 'user', text }])
    try {
      await sendMessage(sessionId, text, onEvent)
    } catch (e) {
      setItems((it) => [...it, { id: ++idRef.current, kind: 'error', text: (e as Error).message }])
    } finally {
      setBusy(false)
    }
  }, [sessionId, busy, onEvent])

  const shown = hypo ?? result
  const candidates = shown ? [...shown.ranked, ...shown.excluded] : []
  const activeCandidate = candidates.find((d) => d.dong_code === selected) ?? shown?.ranked[0]
  function focusSearch() {
    setMobileView('chat')
    requestAnimationFrame(() => document.getElementById('condition-input')?.focus())
  }

  function openComparison(code: string) {
    setSelected(code)
    setTab('compare')
  }

  // 답변 속 동네 표에서 "지도에서 보기"
  function focusDong(code: string) {
    setSelected(code)
    setTab('map')
    setMobileView('results')
  }

  return (
    <div className="app" data-mobile-view={error ? 'results' : mobileView}>
      <StationSign state={state} busy={busy} onReset={() => load(true)} />

      {!error && <div className="mobile-navigation" role="group" aria-label="화면 선택">
        <button type="button" aria-pressed={mobileView === 'chat'} onClick={() => setMobileView('chat')}>조건 입력</button>
        <button type="button" aria-pressed={mobileView === 'results'} onClick={() => setMobileView('results')}>결과 보기</button>
      </div>}

      <aside className="chat-col" aria-label="대화">
        <Chat items={items} busy={busy} onSend={send} disabled={!sessionId} hasResult={!!result} onFocusDong={focusDong} />
      </aside>

      <main className="work-col">
        {error && <div className="banner banner-error" role="alert">
          {error} <button type="button" className="link-btn" onClick={() => load(false)}>다시 연결</button>
        </div>}

        {hypo && (
          <p className="banner banner-hypo">
            가정해 본 결과예요. 실제 조건은 그대로입니다. 바꾸려면 "통근 30분 이내로 바꿔줘"처럼 말해 주세요.
            <button className="link-btn" onClick={() => setHypo(null)}>현재 결과로 돌아가기</button>
          </p>
        )}
        {shown?.tradeoffs.map((t) => (
          <p key={t.factors.join()} className="banner banner-warn">
            <strong>{t.factors[0]}와(과) {t.factors[1]}는 함께 얻기 어려워요.</strong> {t.message}.
          </p>
        ))}
        {shown?.notes.map((n) => <p key={n} className="banner banner-warn">{n}</p>)}

        {shown && <header className="result-heading">
          <div>
            <h1>{shown.destination.place_name || shown.destination.key} 주변 동네</h1>
            <p>후보 {shown.universe_size}곳 · 비교 {shown.ranked.length}곳</p>
          </div>
          <button type="button" className="btn-ghost" onClick={focusSearch}>조건 바꾸기</button>
        </header>}

        {shown && <nav className="tabs" aria-label="결과 보기">
          {TABS.map((t) => (
            <button type="button" key={t.key} aria-pressed={tab === t.key}
              className={tab === t.key ? 'tab is-active' : 'tab'} onClick={() => setTab(t.key)}>
              {t.label}
            </button>
          ))}
        </nav>}

        <section className="stage">
          {shown && !shown.ranked.length && (
            <div className="mascot-status">
              <img src="/setter-mascot-thinking.png" width="48" height="54" alt="" />
              <p>추천 후보가 없어요. 예산이나 통근 조건을 조정해 보세요.</p>
              <button type="button" className="link-btn" onClick={focusSearch}>조건 바꾸기</button>
            </div>
          )}
          {!shown ? (
            <div className="empty">
              <div className="empty-copy">
                <h1 className="empty-title">내 일상에 맞는 동네 찾기</h1>
                <p>출근하는 곳과 예산을 말해 주세요. 동네마다 비용과 통근 시간을 비교해 볼 수 있어요.</p>
                <button type="button" className="btn-primary" onClick={focusSearch} disabled={!sessionId}>조건 입력하기</button>
              </div>
              <img className="empty-mascot" src="/setter-mascot.png" width="384" height="434" alt="" />
              <ul className="empty-factors" aria-label="비교 기준">
                {FACTORS.map((factor) => (
                  <li key={factor.key}><span className="pref-dot" style={{ background: factor.color }} />{factor.label}</li>
                ))}
              </ul>
            </div>
          ) : tab === 'map' ? (
            <>
              <MapView result={shown} selected={selected} onSelect={setSelected} />
              {activeCandidate && (
                <section className="candidate-summary" aria-label="지도 후보 요약">
                  <header>
                    <div className="candidate-heading">
                      <img src="/setter-mascot-guide.png" width="40" height="45" alt="" />
                      <h2>{activeCandidate.name} <small>{activeCandidate.sgg}</small></h2>
                    </div>
                    <button type="button" className="btn-ghost" onClick={() => openComparison(activeCandidate.dong_code)}>비교에서 보기</button>
                  </header>
                  <dl>
                    {FACTORS.map((f) => (
                      <div key={f.key}>
                        <dt>{f.key === 'quiet' ? '주변 주점' : f.label}</dt>
                        <dd>{rawText(f.key, activeCandidate.raw[f.key])}</dd>
                      </div>
                    ))}
                  </dl>
                </section>
              )}
            </>
          ) : tab === 'table' ? (
            <RankingTable result={shown} onCompare={openComparison} />
          ) : tab === 'tradeoff' ? (
            <TradeoffChart result={shown} selected={selected} onSelect={setSelected} />
          ) : (
            <CompareCards result={shown} selected={selected} conversionRate={state?.params.conversion_rate ?? 0.05} />
          )}
        </section>

        <div className="lower">
          <DiffPanel diff={shown?.diff ?? null} />
          <AgentLine logs={logs} busy={busy} />
        </div>

        {shown && (
          <footer className="sources">
            <p>
              실거래가는 {shown.rent_period.replace(/(\d{4})(\d{2})~(\d{4})(\d{2})/, '$1년 $2월 ~ $3년 $4월')} 계약 기준 시세 참고용이며,
              현재 매물 가격이 아닙니다. 관리비·치안·집 상태는 데이터가 없어 직접 확인해야 해요.
            </p>
            <details>
              <summary>데이터 출처 보기</summary>
              <dl>
              {Object.entries(shown.sources).map(([k, v]) => (
                <div key={k}><dt>{k}</dt><dd>{v}</dd></div>
              ))}
              </dl>
            </details>
          </footer>
        )}
      </main>
    </div>
  )
}
