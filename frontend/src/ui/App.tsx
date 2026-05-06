import { useEffect, useState } from 'react'
import { Link, NavLink, Route, Routes } from 'react-router-dom'
import AlertsPage from './AlertsPage'
import InstancesPage from './InstancesPage'
import InstanceDetailPage from './InstanceDetailPage'
import ModelsPage from './ModelsPage'
import RunsPage from './RunsPage'

type Theme = 'light' | 'dark'

function applyTheme(t: Theme) {
  const el = document.documentElement
  if (t === 'dark') el.classList.add('dark')
  else el.classList.remove('dark')
}

function readInitialTheme(): Theme {
  const saved = localStorage.getItem('openports.theme') as Theme | null
  if (saved === 'light' || saved === 'dark') return saved
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

export default function App() {
  const [theme, setTheme] = useState<Theme>(readInitialTheme)

  useEffect(() => {
    applyTheme(theme)
    localStorage.setItem('openports.theme', theme)
  }, [theme])

  return (
    <div className="app-shell">
      <header className="app-header">
        <Link to="/" className="plain app-title">
          <span className="dot" />
          openports
        </Link>
        <nav className="app-nav">
          <NavLink to="/" end className={({ isActive }) => (isActive ? 'active plain' : 'plain')}>
            instances
          </NavLink>
          <NavLink to="/models" className={({ isActive }) => (isActive ? 'active plain' : 'plain')}>
            models
          </NavLink>
          <NavLink to="/alerts" className={({ isActive }) => (isActive ? 'active plain' : 'plain')}>
            alerts
          </NavLink>
          <NavLink to="/runs" className={({ isActive }) => (isActive ? 'active plain' : 'plain')}>
            scans
          </NavLink>
        </nav>
        <div className="app-spacer" />
        <button
          className="ghost icon"
          title={theme === 'dark' ? 'switch to light' : 'switch to dark'}
          onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
        >
          {theme === 'dark' ? '☀' : '☾'}
        </button>
      </header>

      <Routes>
        <Route path="/" element={<InstancesPage />} />
        <Route path="/instances/:id" element={<InstanceDetailPage />} />
        <Route path="/models" element={<ModelsPage />} />
        <Route path="/alerts" element={<AlertsPage />} />
        <Route path="/runs" element={<RunsPage />} />
      </Routes>
    </div>
  )
}
