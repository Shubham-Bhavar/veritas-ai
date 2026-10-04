import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router'
import { api, session } from './api.js'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => (session.token() ? session.user() : null))
  const [expired, setExpired] = useState(false)
  const navigate = useNavigate()

  useEffect(() => {
    session.onUnauthorized(() => {
      setExpired(true)
      setUser(null)
      navigate('/login', { replace: true, state: { expired: true } })
    })
    // A signed token can outlive its account (database reset, guest cleanup): check once on load.
    if (session.token()) {
      api.me().catch(() => {}) // a 401 triggers onUnauthorized above
    }
  }, [navigate])

  const accept = useCallback((res) => {
    session.set(res.token, res.user)
    setExpired(false)
    setUser(res.user)
    return res.user
  }, [])

  const value = useMemo(
    () => ({
      user,
      expired,
      guest: async () => accept(await api.guest()),
      login: async (email, password) => accept(await api.login(email, password)),
      register: async (name, email, password) => accept(await api.register(name, email, password)),
      logout: () => {
        session.clear()
        setUser(null)
        navigate('/', { replace: true })
      },
    }),
    [user, expired, accept, navigate],
  )
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  return useContext(AuthContext)
}
