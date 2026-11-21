import { useEffect, useRef, useState } from 'react'

import { CONSTRAINT_LABEL, FACTOR, constraintText } from '../lib/format'
import type { ConstraintKey, FactorKey, Interpretation } from '../lib/types'

export type ChatItem =
  | { id: number; kind: 'user' | 'assistant'; text: string; source?: 'llm' | 'template' }
  | { id: number; kind: 'interpretation'; interp: Interpretation }
  | { id: number; kind: 'error'; text: string }

const EXAMPLES = [
  '판교역으로 출근해요. 보증금 1000에 월세 60 넘으면 안 되고, 싼 게 제일 중요해요.',
  '통근은 50분까지 괜찮고, 조용한 동네였으면 좋겠어요.',
  '아까보다 역 가까운 게 더 중요해요.',
  '통근 30분 이내로 줄이면 어떻게 돼?',
]

export default function Chat({ items, busy, disabled, onSend }: {
  items: ChatItem[]; busy: boolean; disabled: boolean; onSend: (t: string) => void
}) {
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)

  useEffect(() => { endRef.current?.scrollIntoView({ block: 'end' }) }, [items, busy])

  const submit = () => {
    const t = text.trim()
    if (!t || busy || disabled) return
    onSend(t)
    setText('')
  }

  return (
    <div className="chat">
      <div className="chat-log" aria-live="polite">
        {items.length === 0 && (
          <div className="chat-intro">
            <p>어디로 출근하는지, 보증금과 월세는 얼마까지인지, 무엇이 중요한지 평소 말하듯 적어 주세요.</p>
            <p className="chat-intro-sub">예시를 누르면 입력창에 들어가요.</p>
            <ul className="examples">
              {EXAMPLES.map((e) => (
                <li key={e}><button onClick={() => setText(e)}>{e}</button></li>
              ))}
            </ul>
          </div>
        )}
        {items.map((it) =>
          it.kind === 'interpretation' ? <InterpretationCard key={it.id} it={it.interp} />
            : it.kind === 'error' ? <p key={it.id} className="bubble bubble-error" role="alert">{it.text}</p>
              : (
                <div key={it.id} className={`bubble bubble-${it.kind}`}>
                  {it.text}
                  {it.kind === 'assistant' && it.source === 'template' && <span className="bubble-note">자동 요약</span>}
                </div>
              ),
        )}
        {busy && <p className="typing">조건을 확인하고 동네를 비교하는 중…</p>}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); submit() }}>
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            // 한글 입력 조합 중의 Enter 는 보내지 않는다
            if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault()
              submit()
            }
          }}
          placeholder="예: 강남역으로 출근하고 월세는 70까지 괜찮아요"
          rows={3}
          disabled={disabled}
          aria-label="조건 입력"
        />
        <div className="composer-row">
          <span className="composer-note">이름·연락처 같은 개인정보는 적지 마세요. 입력한 문장은 AI(Gemini)로 보내져요.</span>
          <button type="submit" className="btn-primary" disabled={busy || disabled || !text.trim()}>보내기</button>
        </div>
      </form>
    </div>
  )
}

function InterpretationCard({ it }: { it: Interpretation }) {
  const cons = it.applied.filter((a) => a.type === 'constraint')
  const prefs = it.applied.filter((a) => a.type === 'preference')
  const params = it.applied.filter((a) => a.type === 'param' && a.key !== 'destination')
  const nothing = !cons.length && !prefs.length && !params.length && !it.unsupported.length && !it.rejected.length
  return (
    <section className="interp" aria-label="이해한 내용">
      <header className="interp-head">
        이렇게 이해했어요
        {it.what_if && <span className="badge badge-hypo">가정</span>}
      </header>

      {it.destination && (
        <div className="interp-row">
          <span className="interp-key">목적지</span>
          <span>
            {it.destination.label}
            {it.destination.alternatives.length > 1 && (
              <details className="alts">
                <summary>다른 곳인가요?</summary>
                <p>검색 결과: {it.destination.alternatives.join(', ')}. 다르면 회사나 역 이름으로 다시 말해 주세요.</p>
              </details>
            )}
          </span>
        </div>
      )}

      {cons.map((a) => (
        <div key={a.key} className="interp-row">
          <span className="interp-key">필수</span>
          <span>
            {a.after == null
              ? `${CONSTRAINT_LABEL[a.key as ConstraintKey]} 한도 해제`
              : constraintText(a.key as ConstraintKey, Number(a.after))}
          </span>
        </div>
      ))}

      {prefs.map((a) => {
        const f = FACTOR[a.key as FactorKey]
        return (
          <div key={a.key} className="interp-row">
            <span className="interp-key">선호</span>
            <span>
              <span className="pref-dot" style={{ background: f?.color }} aria-hidden="true" />
              {f?.label ?? a.key} {String(a.before)} → <strong>{String(a.after)}</strong>
              {a.evidence && <q className="evidence">{a.evidence}</q>}
            </span>
          </div>
        )
      })}

      {params.map((a) => (
        <div key={a.key} className="interp-row">
          <span className="interp-key">기준</span>
          <span>{a.key === 'house_types' ? `주택 유형: ${(a.after as string[]).join(', ')}` : `${a.key}: ${String(a.after)}`}</span>
        </div>
      ))}

      {it.comparison_fixes.length > 0 && (
        <p className="interp-note">말씀하신 우선순위에 맞게 단계를 조정했어요.</p>
      )}

      {it.unsupported.length > 0 && (
        <div className="interp-unsupported">
          <p>데이터로 확인할 수 없어 직접 확인이 필요해요</p>
          <ul>{it.unsupported.map((u) => <li key={u}>{u}</li>)}</ul>
        </div>
      )}

      {it.rejected.length > 0 && (
        <div className="interp-rejected">
          반영하지 못한 내용: {it.rejected.map((r) => `${r.item} (${r.reason})`).join(', ')}
        </div>
      )}

      {nothing && !it.destination && <p className="interp-note">바뀐 조건은 없어요.</p>}
    </section>
  )
}
