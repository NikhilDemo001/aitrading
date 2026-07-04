import { useMemo, useRef } from 'react'
import { useFrame } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { Scene3DPanel } from '../Scene3DPanel'

// Decorative capital-flow visualization (no live data source in the backend for this,
// mirrors the legacy CapitalGlobe scene's role) — a wireframe globe with an orbiting dust
// ring, in the CIPHER·TERMINAL neon palette (cyan globe, cyber-green dust).
function GlobeContent({ isVisible }: { isVisible: boolean }) {
  const globeRef = useRef<THREE.Mesh>(null)
  const ringRef = useRef<THREE.Points>(null)

  const ringGeometry = useMemo(() => {
    const count = 400
    const positions = new Float32Array(count * 3)
    for (let i = 0; i < count; i++) {
      const angle = Math.random() * Math.PI * 2
      const radius = 2.6 + Math.random() * 0.5
      const tilt = (Math.random() - 0.5) * 0.6
      positions[i * 3] = Math.cos(angle) * radius
      positions[i * 3 + 1] = tilt
      positions[i * 3 + 2] = Math.sin(angle) * radius
    }
    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    return geo
  }, [])

  useFrame((_, delta) => {
    if (!isVisible) return
    if (globeRef.current) globeRef.current.rotation.y += delta * 0.15
    if (ringRef.current) ringRef.current.rotation.y -= delta * 0.08
  })

  return (
    <>
      <ambientLight intensity={0.6} />
      <pointLight position={[5, 5, 5]} intensity={40} color="#00F0FF" />
      <mesh ref={globeRef}>
        <icosahedronGeometry args={[2, 3]} />
        <meshBasicMaterial color="#00F0FF" wireframe transparent opacity={0.35} />
      </mesh>
      <points ref={ringRef} geometry={ringGeometry}>
        <pointsMaterial color="#00E676" size={0.035} transparent opacity={0.8} />
      </points>
      <OrbitControls enableZoom={false} enablePan={false} autoRotate={false} />
    </>
  )
}

export function CapitalGlobeScene() {
  return (
    <Scene3DPanel title="Capital Flow">
      {({ isVisible }) => <GlobeContent isVisible={isVisible} />}
    </Scene3DPanel>
  )
}
