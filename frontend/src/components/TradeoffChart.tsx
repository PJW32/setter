import { CartesianGrid, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from 'recharts'

import { fmt, won } from '../lib/format'
import type { ResultPayload } from '../lib/types'

type Props = { result: ResultPayload; selected: string | null; onSelect: (c: string) => void }
type Pt = { dong_code: string; name: string; rank: number; x: number; y: number; pareto: boolean; estimated: boolean }

const INK = '#15222B'
const MUTED = '#9fb0b8'

/** 가로 월 총비용, 세로 통근 시간. 둘 다 더 나은 동이 없는 동(파레토)을 선으로 잇는다 */
export default function TradeoffChart({ result, selected, onSelect }: Props) {
  const pts = result.scatter.filter((p) => p.x != null && p.y != null) as Pt[]
  const front = pts.filter((p) => p.pareto).sort((a, b) => a.x - b.x)
  const rest = pts.filter((p) => !p.pareto)
  const missing = result.scatter.length - pts.length

  return (
    <div className="tradeoff">
      <p className="chart-lede">
        왼쪽 아래로 갈수록 싸고 가까워요. 진한 점을 이은 선은 <strong>더 싸면서 더 가까운 동네가 없는</strong> 선택지예요.
        선 위의 동네끼리는 돈과 시간을 맞바꾸는 관계입니다.
      </p>
      <div className="chart-box">
        <ResponsiveContainer width="100%" height="100%">
          <ScatterChart margin={{ top: 16, right: 24, bottom: 28, left: 8 }}>
            <CartesianGrid stroke="#e3e8ea" />
            <XAxis type="number" dataKey="x" name="월 총비용" unit="만" domain={['dataMin - 2', 'dataMax + 2']}
              tickFormatter={(v) => fmt(v, 0)} stroke="#8a969c" fontSize={12}
              label={{ value: '월 총비용 (만 원)', position: 'insideBottom', offset: -16, fill: '#56656D', fontSize: 12 }} />
            <YAxis type="number" dataKey="y" name="통근" domain={[0, 'dataMax + 5']} stroke="#8a969c" fontSize={12}
              label={{ value: '통근 (분)', angle: -90, position: 'insideLeft', fill: '#56656D', fontSize: 12 }} />
            <Tooltip cursor={{ strokeDasharray: '3 3' }} content={<Tip />} />
            <Scatter data={rest} fill={MUTED} onClick={(p) => onSelect((p as unknown as Pt).dong_code)}
              shape={(props: unknown) => <Dot {...(props as DotProps)} selected={selected} />} />
            <Scatter data={front} fill={INK} line={{ stroke: INK, strokeWidth: 2 }} lineType="joint"
              onClick={(p) => onSelect((p as unknown as Pt).dong_code)}
              shape={(props: unknown) => <Dot {...(props as DotProps)} selected={selected} strong />} />
          </ScatterChart>
        </ResponsiveContainer>
      </div>
      <p className="chart-foot">
        숫자는 순위. 속이 빈 점은 실거래가 적어 월 총비용을 추정한 동네예요.
        {missing > 0 && ` 값이 없는 ${missing}곳은 그리지 않았어요.`}
      </p>
    </div>
  )
}

type DotProps = { cx: number; cy: number; payload: Pt; selected: string | null; strong?: boolean }

function Dot({ cx, cy, payload, selected, strong }: DotProps) {
  const isSel = payload.dong_code === selected
  const r = isSel ? 8 : strong ? 6 : 5
  const color = strong ? INK : MUTED
  return (
    <g style={{ cursor: 'pointer' }}>
      <circle cx={cx} cy={cy} r={r + 2} fill="#fff" />
      <circle cx={cx} cy={cy} r={r} fill={payload.estimated ? '#fff' : color} stroke={color} strokeWidth={2} />
      {isSel && <circle cx={cx} cy={cy} r={r + 4} fill="none" stroke={INK} strokeWidth={1.5} />}
      {(payload.rank <= 3 || isSel) && (
        <text x={cx + r + 4} y={cy - r} fontSize={12} fontWeight={700} fill={INK}>
          {payload.rank} {payload.name}
        </text>
      )}
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
