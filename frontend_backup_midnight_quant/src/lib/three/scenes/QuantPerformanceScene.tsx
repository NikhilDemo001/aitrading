import { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useFrame } from '@react-three/fiber'
import { OrbitControls, Html } from '@react-three/drei'
import gsap from 'gsap'
import * as THREE from 'three'
import { Scene3DPanel } from '../Scene3DPanel'
import { researchApi, type LeaderboardEntry } from '../../api/researchApi'

const BAR_COUNT = 10
const MAX_HEIGHT = 2.4

function scaleHeight(expectancy: number, maxAbs: number) {
  if (maxAbs === 0) return 0.05
  return Math.max(0.05, (Math.abs(expectancy) / maxAbs) * MAX_HEIGHT)
}

function Bars({ entries, isVisible }: { entries: LeaderboardEntry[]; isVisible: boolean }) {
  const groupRef = useRef<THREE.Group>(null)
  const barRefs = useRef<Array<THREE.Mesh | null>>([])
  const [hovered, setHovered] = useState<number | null>(null)

  const maxAbs = useMemo(() => Math.max(1, ...entries.map((e) => Math.abs(e.expectancy))), [entries])

  useEffect(() => {
    // Real leaderboard-driven "grow in" animation replacing the legacy hardcoded array.
    barRefs.current.forEach((mesh, i) => {
      if (!mesh) return
      const target = scaleHeight(entries[i]?.expectancy ?? 0, maxAbs)
      gsap.fromTo(mesh.scale, { y: 0.001 }, { y: target, duration: 0.6, delay: i * 0.04, ease: 'power2.out' })
      mesh.position.y = target / 2
    })
  }, [entries, maxAbs])

  useFrame((_, delta) => {
    if (!isVisible || !groupRef.current) return
    groupRef.current.rotation.y += delta * 0.05
  })

  const spacing = 0.55
  const offset = ((entries.length - 1) * spacing) / 2

  return (
    <group ref={groupRef}>
      {entries.map((entry, i) => {
        const positive = entry.expectancy >= 0
        return (
          <mesh
            key={entry.id}
            ref={(m) => { barRefs.current[i] = m }}
            position={[i * spacing - offset, 0.025, 0]}
            onPointerOver={() => setHovered(i)}
            onPointerOut={() => setHovered((h) => (h === i ? null : h))}
          >
            <boxGeometry args={[0.32, 1, 0.32]} />
            <meshStandardMaterial color={positive ? '#34D399' : '#F43F5E'} emissive={positive ? '#0F3A2C' : '#3A0F18'} />
            {hovered === i && (
              <Html center distanceFactor={8} style={{ pointerEvents: 'none' }}>
                <div className="mq-quant-tooltip">
                  <strong>{entry.name}</strong>
                  <span>Expectancy ₹{entry.expectancy.toFixed(2)}</span>
                  <span>PF {entry.profit_factor.toFixed(2)} · {entry.status}</span>
                </div>
              </Html>
            )}
          </mesh>
        )
      })}
    </group>
  )
}

export function QuantPerformanceScene() {
  const { data } = useQuery({
    queryKey: ['research', 'leaderboard'],
    queryFn: researchApi.getLeaderboard,
    refetchInterval: 30000,
  })
  const entries = (data ?? []).slice(0, BAR_COUNT)

  return (
    <Scene3DPanel title="Quant Performance · live leaderboard">
      {({ isVisible }) =>
        entries.length > 0 ? (
          <>
            <ambientLight intensity={0.7} />
            <pointLight position={[4, 5, 4]} intensity={30} color="#7C6CFF" />
            <Bars entries={entries} isVisible={isVisible} />
            <OrbitControls enableZoom={false} enablePan={false} />
          </>
        ) : null
      }
    </Scene3DPanel>
  )
}
