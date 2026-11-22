import { FACTORS, fmt, rawText, violationText, won } from '../lib/format'
import type { DongCard, ResultPayload } from '../lib/types'
import { Flags, ScoreBar } from './RankingTable'

type Props = { result: ResultPayload; selected: string | null; conversionRate: number }

/** 상위 3곳 (고른 동이 3위 밖이면 그 동을 마지막 칸에) */
export default function CompareCards({ result, selected, conversionRate }: Props) {
  const top = result.ranked.slice(0, 3)
  const all = [...result.ranked, ...result.excluded]
  const sel = selected ? all.find((d) => d.dong_code === selected) : undefined
  const cards = sel && !top.some((d) => d.dong_code === sel.dong_code) ? [...top.slice(0, 2), sel] : top

  if (!cards.length) return <p className="panel-empty">조건을 만족하는 동네가 없어요. 조건을 조금 풀어 보세요.</p>
  return (
    <div className="compare">
      {cards.map((d) => <Card key={d.dong_code} d={d} rate={conversionRate} />)}
    </div>
  )
}

function Card({ d, rate }: { d: DongCard; rate: number }) {
  const c = d.cost
  const depositMonthly = c.median_deposit != null ? (c.median_deposit * rate) / 12 : null
  const q = encodeURIComponent(`${d.sgg} ${d.name}`)
  return (
    <article className="card">
      <header className="card-head">
        <span className="card-rank">{d.rank ? `${d.rank}위` : '조건 밖'}</span>
        <h3>{d.name}</h3>
        <span className="dong-sgg">{d.sgg}</span>
      </header>
      <ScoreBar d={d} />

      <section className="card-sec">
        <h4>월 총비용 {c.monthly_total != null ? won(c.monthly_total) : '데이터 부족'}</h4>
        <dl className="kv">
          <div><dt>월세 중앙값</dt><dd>{won(c.median_rent)}</dd></div>
          <div><dt>보증금 중앙값</dt><dd>{won(c.median_deposit)} {depositMonthly != null && <small>(월 약 {fmt(depositMonthly)}만 원으로 환산)</small>}</dd></div>
          <div><dt>월 교통비</dt><dd>{c.fare_month != null ? won(c.fare_month) : '요금 정보 없음'}</dd></div>
          <div><dt>실거래 표본</dt><dd>{c.samples}건</dd></div>
        </dl>
        <p className="fine">항목마다 중앙값이라 합이 월 총비용과 꼭 같지는 않아요. 관리비는 포함되지 않아요.</p>
      </section>

      <section className="card-sec">
        <h4>통근 {d.commute.min != null ? `${d.commute.min}분` : '데이터 없음'}</h4>
        <p>
          {d.commute.mode}{d.commute.lines?.length ? ` · ${d.commute.lines.join(', ')}` : ''}
          {d.commute.transfers ? ` · 환승 ${d.commute.transfers}회` : ''}
          {d.commute.walk_from_station ? ` · 역에서 도보 ${d.commute.walk_from_station}분 포함` : ''}
        </p>
        {d.commute.map_url && <a href={d.commute.map_url} target="_blank" rel="noreferrer">카카오맵에서 경로 보기</a>}
      </section>

      <section className="card-sec">
        <h4>생활</h4>
        <dl className="kv">
          <div><dt>가까운 역</dt><dd>{d.station.name ? `${d.station.name} · ${rawText('station_access', d.raw.station_access)} (추정)` : '3km 안에 없음'}</dd></div>
          <div><dt>생활 편의 점수</dt><dd>{rawText('convenience', d.raw.convenience)}</dd></div>
          <div><dt>편의시설</dt><dd>{Object.entries(d.convenience).map(([k, v]) => `${k} ${v}곳`).join(' · ') || '데이터 없음'}</dd></div>
          <div><dt>주변 주점</dt><dd>{d.bars.count == null ? '데이터 없음' : `${d.bars.count}곳 (반경 500m)`}</dd></div>
        </dl>
      </section>
      <p className="fine">조용함은 주변 주점 수로 추정하며, 실제 소음이나 밤길 안전을 뜻하지 않아요.</p>

      <section className="card-sec">
        <h4>점수 구성</h4>
        <ul className="contrib-list">
          {FACTORS.map((f) => (
            <li key={f.key}>
              <span className="swatch" style={{ background: f.color }} />{f.label}
              <span className="num">{fmt(d.contrib[f.key])}점</span>
            </li>
          ))}
        </ul>
      </section>

      <Flags d={d} />
      {d.violations?.map((v, i) => <p key={i} className="why">{violationText(v)}</p>)}

      <footer className="card-links">
        <span>이 동네 매물 찾아보기</span>
        <a href={`https://map.kakao.com/?q=${q}`} target="_blank" rel="noreferrer">카카오맵</a>
        <a href="https://www.zigbang.com/" target="_blank" rel="noreferrer">직방</a>
        <a href="https://www.dabangapp.com/" target="_blank" rel="noreferrer">다방</a>
      </footer>
    </article>
  )
}
