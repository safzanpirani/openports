import { Link, Route, Routes } from 'react-router-dom'
import InstancesPage from './InstancesPage'
import InstanceDetailPage from './InstanceDetailPage'
import RunsPage from './RunsPage'

export default function App() {
  return (
    <div style={{ fontFamily: 'system-ui, sans-serif', padding: 16 }}>
      <header style={{ display: 'flex', gap: 16, alignItems: 'baseline', marginBottom: 16 }}>
        <h2 style={{ margin: 0 }}>openports</h2>
        <nav style={{ display: 'flex', gap: 12 }}>
          <Link to="/">Instances</Link>
          <Link to="/runs">Scan runs</Link>
        </nav>
      </header>

      <Routes>
        <Route path="/" element={<InstancesPage />} />
        <Route path="/instances/:id" element={<InstanceDetailPage />} />
        <Route path="/runs" element={<RunsPage />} />
      </Routes>
    </div>
  )
}
