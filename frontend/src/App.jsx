import { Navigate, Route, Routes, useLocation } from 'react-router'
import { useAuth } from './auth.jsx'
import Landing from './pages/Landing.jsx'
import Login from './pages/Login.jsx'
import Workspace from './pages/Workspace.jsx'
import Investigation from './investigation/Investigation.jsx'

function RequireAuth({ children }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return children
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/app" element={<RequireAuth><Workspace /></RequireAuth>} />
      <Route path="/app/i/:id" element={<RequireAuth><Investigation /></RequireAuth>} />
      <Route path="/app/i/:id/:tab" element={<RequireAuth><Investigation /></RequireAuth>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
