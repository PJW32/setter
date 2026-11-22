import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'

import { fmt, MAP_SCORE_COLORS, scoreColor, won } from '../lib/format'
import type { ResultPayload } from '../lib/types'

type Props = { result: ResultPayload; selected: string | null; onSelect: (c: string) => void; highlight?: string[] }
type Pt = { dong_code: string; name: string; rank: number; x: number; y: number; pareto: boolean; estimated: boolean }

const INK = '#15222B'
const LINE = MAP_SCORE_COLORS[1]
const HI = '#eb6834' // 대화에서 가리킨 동네

/** 가로 월 총비용, 세로 통근 시간. 둘 다 더 나은 동이 없는 동(파레토)을 선으로 잇는다 */
export default function TradeoffChart({ result, selected, onSelect, highlight = [] }: Props) {
  const pts = result.scatter.filter((p) => p.x != null && p.y != null) as Pt[]
  const front = pts.filter((p) => p.pareto).sort((a, b) => a.x - b.x)
  const rest = pts.filter((p) => !p.pareto)
  const missing = result.scatter.length - pts.length
  const hi = new Set(highlight)
  const hiNames = pts.filter((p) => hi.has(p.dong_code)).map((p) => p.name)
  // 고른 동네·물어본 동네의 테두리와 이름은 맨 위 층에 따로 그려 다른 점에 가리지 않게 한다
  const marked = pts.filter((p) => p.dong_code === selected || hi.has(p.dong_code))
  const scores = new Map(result.ranked.map((d) => [d.dong_code, d.score]))
  const low = Math.min(...scores.values())
  const high = Math.max(...scores.values())

  function renderDot(props: unknown, strong = false) {
    const dot = props as DotProps
    const score = scores.get(dot.payload.dong_code)
    const color = dot.payload.rank <= 3 ? 'var(--brand)' : scoreColor(score ?? low, low, high)
    return <Dot {...dot} selected={selected} color={color} strong={strong} hi={hi} />
  }

  return (
    <div className="tradeoff">
      <p className="chart-lede">
        왼쪽 아래로 갈수록 싸고 가까워요. 진한 점을 이은 선은 <strong>더 싸면서 더 가까운 동네가 없는</strong> 선택지예요.<br />
        선 위의 동네끼리는 돈과 시간을 맞바꾸는 관계입니다.
      </p>
      {hiNames.length > 0 && (
        <p className="chart-hi"><span className="chart-hi-dot" aria-hidden="true" />대화에서 물어본 동네: {hiNames.join(', ')}</p>
      )}
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 16, right: 24, bottom: 28, left: 8 }}>
            <CartesianGrid stroke="#e3e8ea" />
            <XAxis type="number" dataKey="x" name="월 총비용" unit="만" domain={['dataMin - 2', 'dataMax + 2']}
              tickFormatter={(v) => fmt(v, 0)} stroke="#8a969c" fontSize={12}
              label={{ value: '월 총비용 (만 원)', position: 'insideBottom', offset: -16, fill: '#56656D', fontSize: 12 }} />
            <YAxis type="number" dataKey="y" name="통근" domain={[0, 'dataMax + 5']} stroke="#8a969c" fontSize={12}
              label={{ value: '통근 (분)', angle: -90, position: 'insideLeft', fill: '#56656D', fontSize: 12 }} />
            <Tooltip
              cursor={{ strokeDasharray: '3 3' }}
              content={<Tip />}
              offset={14}
              reverseDirection={{ y: true }}
              allowEscapeViewBox={{ x: true, y: true }}
            />
            <Scatter data={rest} onClick={(p) => onSelect((p as unknown as Pt).dong_code)}
              shape={(props: unknown) => renderDot(props)} />
            <Scatter data={front} line={{ stroke: LINE, strokeWidth: 2 }} lineType="joint"
              onClick={(p) => onSelect((p as unknown as Pt).dong_code)}
              shape={(props: unknown) => renderDot(props, true)} />
            <Scatter data={marked} isAnimationActive={false} legendType="none" tooltipType="none"
              shape={(props: unknown) => <Mark {...(props as DotProps)} hi={hi} />} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="chart-foot">
        숫자는 순위. 속이 빈 점이나 점선 테두리는 월 총비용을 추정한 동네예요.
        {missing > 0 && ` 값이 없는 ${missing}곳은 그리지 않았어요.`}
      </p>
    </div>
  )
}

type DotProps = { cx: number; cy: number; payload: Pt; selected: string | null; color: string; strong?: boolean; hi: Set<string> }

function Dot({ cx, cy, payload, selected, color, strong, hi }: DotProps) {
  const isSel = payload.dong_code === selected
  const isHi = hi.has(payload.dong_code)
  const isTop = payload.rank >= 1 && payload.rank <= 3
  const r = isTop ? 11 : isSel || isHi ? 8 : strong ? 6 : 5
  const outline = isTop ? '#74511a' : LINE
  return (
    <g style={{ cursor: 'pointer' }}>
      <circle cx={cx} cy={cy} r={r + 2} fill="#fff" />
      <circle cx={cx} cy={cy} r={r} fill={payload.estimated && !isTop ? '#fff' : color} stroke={outline}
        strokeWidth={isTop || strong || payload.estimated ? 2 : 1} strokeDasharray={isTop && payload.estimated ? '3 2' : undefined} />
      {isTop && (
        <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central" fontSize={12} fontWeight={700} fill={INK} pointerEvents="none">
          {payload.rank}
        </text>
      )}
    </g>
  )
}

/** 맨 위 층: 고른 동네·물어본 동네의 테두리와 이름표 (흰 테두리 글자라 겹쳐도 읽힌다) */
function Mark({ cx, cy, payload, hi }: Pick<DotProps, 'cx' | 'cy' | 'payload' | 'hi'>) {
  const isHi = hi.has(payload.dong_code)
  const isTop = payload.rank >= 1 && payload.rank <= 3
  const r = isTop ? 11 : 8
  return (
    <g pointerEvents="none">
      <circle cx={cx} cy={cy} r={r + 4} fill="none" stroke={isHi ? HI : INK} strokeWidth={isHi ? 2.5 : 1.5} />
      <text x={cx + r + 8} y={cy - r - 2} fontSize={12.5} fontWeight={700} fill={INK}
        stroke="#fff" strokeWidth={4} strokeLinejoin="round" paintOrder="stroke">
        {payload.name}
      </text>
    </g>
  )
}

function Tip({ active, payload }: { active?: boolean; payload?: { payload: Pt }[] }) {
  if (!active || !payload?.length) return null
  const p = payload[0].payload
  return (
    <div className="chart-tip">
      <strong>{p.rank}위 {p.name}</strong>
      <div>월 총비용 {won(p.x)}{p.estimated ? ' (추정)' : ''}</div>
      <div>통근 {fmt(p.y, 0)}분</div>
      {p.pareto && <div className="tip-note">더 싸고 더 가까운 곳이 없는 선택지</div>}
    </div>
  )
}
