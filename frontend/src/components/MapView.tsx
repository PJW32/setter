import L from 'leaflet'
import { useEffect, useMemo } from 'react'
import { CircleMarker, MapContainer, Marker, TileLayer, Tooltip, useMap } from 'react-leaflet'

import { fmt, scoreColor, won } from '../lib/format'
import type { DongCard, ResultPayload } from '../lib/types'

type Props = { result: ResultPayload; selected: string | null; onSelect: (c: string) => void }

export default function MapView({ result, selected, onSelect }: Props) {
  const { ranked, excluded, destination } = result
  const [lo, hi] = useMemo(() => {
    const s = ranked.map((d) => d.score)
    return s.length ? [Math.min(...s), Math.max(...s)] : [0, 100]
  }, [ranked])
  const top3 = ranked.slice(0, 3)
  const near = new Set(result.near_misses)

  return (
    <div className="map-wrap">
      <MapContainer center={[destination.lat, destination.lon]} zoom={12} className="map" scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <Fit result={result} selected={selected} />

        {excluded.map((d) => (
          <CircleMarker key={d.dong_code} center={[d.lat, d.lon]} radius={near.has(d.dong_code) ? 6 : 4}
            pathOptions={{ color: '#ffffff', weight: 1.5, fillColor: near.has(d.dong_code) ? '#8a969c' : '#b9c2c6', fillOpacity: 0.9 }}
            eventHandlers={{ click: () => onSelect(d.dong_code) }}>
            <Tooltip>{d.sgg} {d.name} · 조건 밖{near.has(d.dong_code) ? ' (조금만 풀면 들어옴)' : ''}</Tooltip>
          </CircleMarker>
        ))}

        {ranked.slice(3).map((d) => (
          <CircleMarker key={d.dong_code} center={[d.lat, d.lon]} radius={d.dong_code === selected ? 10 : 7}
            pathOptions={{ color: d.dong_code === selected ? '#15222B' : '#ffffff', weight: 2, fillColor: scoreColor(d.score, lo, hi), fillOpacity: 1 }}
            eventHandlers={{ click: () => onSelect(d.dong_code) }}>
            <Tooltip><DongTip d={d} /></Tooltip>
          </CircleMarker>
        ))}

        {top3.map((d) => (
          <Marker key={d.dong_code} position={[d.lat, d.lon]} icon={rankIcon(d.rank ?? 0, d.dong_code === selected)}
            eventHandlers={{ click: () => onSelect(d.dong_code) }} zIndexOffset={1000}>
            <Tooltip direction="top" offset={[0, -14]}><DongTip d={d} /></Tooltip>
          </Marker>
        ))}

        <Marker position={[destination.lat, destination.lon]} icon={destIcon(destination.key)} zIndexOffset={2000} keyboard={false} />
      </MapContainer>

      <div className="map-legend" aria-hidden="true">
        <span className="legend-ramp" /> 점수 낮음 → 높음
        <span className="legend-grey" /> 조건 밖
      </div>
    </div>
  )
}

function DongTip({ d }: { d: DongCard }) {
  return (
    <span className="tip">
      <strong>{d.rank}위 {d.name}</strong> <span className="tip-sgg">{d.sgg}</span><br />
      {fmt(d.score)}점 · 월 {won(d.cost.monthly_total)} · 통근 {fmt(d.raw.commute, 0)}분
    </span>
  )
}

function Fit({ result, selected }: { result: ResultPayload; selected: string | null }) {
  const map = useMap()
  useEffect(() => {
    const pts = [...result.ranked, ...result.excluded].map((d) => [d.lat, d.lon] as [number, number])
    pts.push([result.destination.lat, result.destination.lon])
    map.fitBounds(L.latLngBounds(pts), { padding: [24, 24] })
  }, [map, result])
  useEffect(() => {
    if (!selected) return
    const d = [...result.ranked, ...result.excluded].find((x) => x.dong_code === selected)
    if (d) map.panTo([d.lat, d.lon])
  }, [map, selected, result])
  return null
}

function rankIcon(rank: number, active: boolean) {
  return L.divIcon({
    className: '',
    html: `<span class="pin${active ? ' pin-active' : ''}">${rank}</span>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  })
}

function destIcon(name: string) {
  return L.divIcon({
    className: '',
    html: `<span class="dest-pin"><span class="dest-ring"></span>${name}</span>`,
    iconSize: [0, 0],
    iconAnchor: [0, 0],
  })
}
