import { useEffect, useRef, useState } from 'react'

import { CONSTRAINT_LABEL, FACTOR, constraintText } from '../lib/format'
import type { ConstraintKey, FactorKey, Interpretation } from '../lib/types'

export type ChatItem =
  | { id: number; kind: 'user' | 'assistant'; text: string; source?: 'llm' | 'template' }
  | { id: number; kind: 'interpretation'; interp: Interpretation }
  | { id: number; kind: 'error'; text: string }

const EXAMPLES = [
  '판교역으로 출근해요. 보증금 1000에 월세 60 넘으면 안 되고, 싼 게 제일 중요해요.',
  '강남역까지 40분 이내면 좋겠어요. 지하철역이 가깝고 마트가 많은 동네를 찾아줘.',
  '광화문역으로 출근해요. 월세는 70만 원까지, 주변에 주점이 적은 곳이면 좋겠어요.',
]

const FOLLOW_UPS = [
  ['예산 조정', '월세를 60만 원 이하로 바꿔줘.'],
  ['통근 시간 비교', '통근을 30분 이내로 줄이면 어떤 동네가 나와?'],
  ['조용한 동네', '주변 주점이 적은 동네를 더 중요하게 봐줘.'],
]

export default function Chat({ items, busy, disabled, onSend, hasResult }: {
  items: ChatItem[]; busy: boolean; disabled: boolean; onSend: (t: string) => void; hasResult: boolean
}) {
  const [text, setText] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  function fillPrompt(prompt: string) {
    setText(prompt)
    inputRef.current?.focus()
  }

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
            <h2>어떤 동네를 찾고 있나요?</h2>
            <p>아래 예시를 골라 내 조건에 맞게 바꿔 보세요.</p>
            <ul className="examples">
              {EXAMPLES.map((e) => (
                <li key={e}><button type="button" disabled={disabled || !!text.trim()} onClick={() => fillPrompt(e)}>{e}</button></li>
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
        {busy && <div className="mascot-status typing" role="status">
          <img src="/setter-mascot-exploring.png" width="40" height="45" alt="" />
          <p>조건을 확인하고 동네를 비교하는 중…</p>
        </div>}
        <div ref={endRef} />
      </div>

      <form className="composer" onSubmit={(e) => { e.preventDefault(); submit() }}>
        {hasResult && !busy && !text.trim() && (
          <div className="follow-ups" role="group" aria-label="조건 변경 예시">
            {FOLLOW_UPS.map(([label, prompt]) => (
              <button type="button" className="btn-ghost" key={label} disabled={disabled} onClick={() => fillPrompt(prompt)}>{label}</button>
            ))}
          </div>
        )}
        <textarea
          id="condition-input"
          ref={inputRef}
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
          maxLength={4000}
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
