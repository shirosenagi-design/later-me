import { useCallback, useEffect, useState } from 'react'
import './App.css'
import CreateCallPreview, { type ReservationInput } from './CreateCallPreview'
import Onboarding, { type FirstRunProfileInput, type ProfileLanguage } from './Onboarding'

type DeliveryState = { state?: string; coherent?: boolean; mode?: string; error_code?: string | null }
type PendingCall = { status: string; scheduled_for: string; created_at?: string; updated_at?: string; future_message?: string | null; delivery?: DeliveryState | null }
type HistoryItem = { occurred_at?: string | null; content?: string | null; demo_sample?: boolean }
type ProfileStatus = { completed: boolean; language: ProfileLanguage | null; phone_registered: boolean }
type AppState = { pending: PendingCall | null; history: HistoryItem[]; completed_call_count: number }
type View = 'home' | 'create' | 'change' | 'history'
type PublicDemoState = { profile: ProfileStatus; data: AppState }

const PUBLIC_DEMO = import.meta.env.VITE_PUBLIC_DEMO === '1'
const PUBLIC_DEMO_STORAGE_KEY = 'later-me-interactive-demo-v1'
const EMPTY_STATE: AppState = { pending: null, history: [], completed_call_count: 0 }
const DEMO_SAMPLE: HistoryItem = {
  occurred_at: '2026-08-24T00:24:00+09:00',
  content: '雨の日の帰り道に、温かい飲み物の話をした。次は、急がず一息つけたかを聞いてみる。',
  demo_sample: true,
}
const DEFAULT_DEMO_STATE: PublicDemoState = {
  profile: { completed: false, language: null, phone_registered: false },
  data: { pending: null, history: [DEMO_SAMPLE], completed_call_count: 1 },
}

const dateFormat = new Intl.DateTimeFormat('ja-JP', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' })
const timeFormat = new Intl.DateTimeFormat('ja-JP', { hour: '2-digit', minute: '2-digit', hour12: false })

function countdown(target: Date, now: Date) {
  const total = Math.max(0, Math.ceil((target.getTime() - now.getTime()) / 60000))
  const days = Math.floor(total / 1440)
  const hours = Math.floor((total % 1440) / 60)
  const minutes = total % 60
  return total === 0 ? 'そろそろ、電話の時間。' : `あと ${days ? `${days}日 ` : ''}${hours ? `${hours}時間 ` : ''}${minutes}分`
}

function readPublicDemoState(): PublicDemoState {
  if (!PUBLIC_DEMO) return DEFAULT_DEMO_STATE
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PUBLIC_DEMO_STORAGE_KEY) || '') as Partial<PublicDemoState>
    const language = parsed.profile?.language === 'en' || parsed.profile?.language === 'ja' ? parsed.profile.language : null
    const profile: ProfileStatus = parsed.profile?.completed === true && language
      ? { completed: true, language, phone_registered: true }
      : DEFAULT_DEMO_STATE.profile
    const storedData = parsed.data
    const pending = storedData?.pending && typeof storedData.pending.scheduled_for === 'string'
      ? storedData.pending
      : null
    const history = Array.isArray(storedData?.history) && storedData.history.length
      ? storedData.history
      : [DEMO_SAMPLE]
    const completedCallCount = typeof storedData?.completed_call_count === 'number' && storedData.completed_call_count >= 1
      ? storedData.completed_call_count
      : 1
    return { profile, data: { pending, history, completed_call_count: completedCallCount } }
  } catch {
    return DEFAULT_DEMO_STATE
  }
}

function persistPublicDemoState(profile: ProfileStatus, data: AppState) {
  if (!PUBLIC_DEMO) return
  window.localStorage.setItem(PUBLIC_DEMO_STORAGE_KEY, JSON.stringify({ profile, data }))
}

function PublicDemoNotice() {
  if (!PUBLIC_DEMO) return null
  return (
    <aside className="public-demo-banner" role="note">
      <strong>INTERACTIVE DEMO — No phone call will be placed. CALL-E is not contacted.</strong>
      <span>Real CALL-E calling is shown in the submission video and available in the Judge Build.</span>
    </aside>
  )
}

const qaInstanceId = import.meta.env.VITE_CALL_E_QA_INSTANCE_ID?.trim()

async function isolatedQaHeaders(init?: RequestInit): Promise<Record<string, string>> {
  const method = (init?.method || 'GET').toUpperCase()
  if (!qaInstanceId || method === 'GET') return {}
  const response = await fetch('/api/health', { headers: { Accept: 'application/json' } })
  const health = await response.json()
  if (!response.ok || health.storage_mode !== 'isolated' || health.instance_id !== qaInstanceId || health.dispatch_enabled !== false) {
    throw new Error('QA用の隔離された予約サービスを確認できません。保存は行われませんでした。')
  }
  return { 'X-CALL-E-QA-Instance': qaInstanceId }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const qaHeaders = await isolatedQaHeaders(init)
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...qaHeaders, ...init?.headers } })
  const body = await response.json()
  if (!response.ok) throw new Error(body.error || '接続できませんでした。')
  return body as T
}

function App() {
  const [demoInitial] = useState(readPublicDemoState)
  const [data, setData] = useState<AppState>(PUBLIC_DEMO ? demoInitial.data : EMPTY_STATE)
  const [profile, setProfile] = useState<ProfileStatus | null>(PUBLIC_DEMO ? demoInitial.profile : null)
  const [view, setView] = useState<View>('home')
  const [now, setNow] = useState(new Date())
  const [loading, setLoading] = useState(!PUBLIC_DEMO)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const refresh = useCallback(async () => {
    if (PUBLIC_DEMO) {
      const current = readPublicDemoState()
      setData(current.data)
      setProfile(current.profile)
      setError('')
      setLoading(false)
      return
    }
    try {
      const [nextData, nextProfile] = await Promise.all([
        api<AppState>('/api/state'),
        api<ProfileStatus>('/api/profile'),
      ])
      setData(nextData)
      setProfile(nextProfile)
      setError('')
    } catch {
      setError('ローカルの予約サービスに接続できません。Python APIを起動してください。')
    } finally {
      setLoading(false)
    }
  }, [])

  // Polling synchronizes React with the local Python booking store outside public demo mode.
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    void refresh()
    if (PUBLIC_DEMO) return
    const poll = window.setInterval(refresh, 30000)
    return () => window.clearInterval(poll)
  }, [refresh])

  useEffect(() => {
    const timer = window.setInterval(() => setNow(new Date()), 1000)
    return () => window.clearInterval(timer)
  }, [])

  const submitReservation = async (input: ReservationInput) => {
    setBusy(true)
    setError('')
    try {
      if (PUBLIC_DEMO) {
        const selected = new Date(input.scheduled_for.replace(' ', 'T'))
        const minimum = new Date(Date.now() + 4 * 60 * 60 * 1000)
        const maximum = new Date()
        maximum.setFullYear(maximum.getFullYear() + 10)
        if (!Number.isFinite(selected.getTime()) || selected < minimum || selected > maximum) {
          throw new Error('今から4時間以上、10年以内の時間を選んでください。')
        }
        if (view === 'create' && data.pending) {
          throw new Error('予約できる電話は、一度に一本だけです。')
        }
        const timestamp = new Date().toISOString()
        const nextPending: PendingCall = {
          status: 'pending_local',
          scheduled_for: selected.toISOString(),
          created_at: view === 'change' ? data.pending?.created_at : timestamp,
          updated_at: timestamp,
          future_message: view === 'change' ? data.pending?.future_message : input.future_message.trim() || null,
          delivery: { state: 'demo_scheduled', coherent: true, mode: 'public_demo' },
        }
        const nextData = { ...data, pending: nextPending }
        setData(nextData)
        persistPublicDemoState(profile || DEFAULT_DEMO_STATE.profile, nextData)
        setView('home')
        return
      }
      const path = view === 'change' ? '/api/calls/change' : '/api/calls'
      const result = await api<{ pending: PendingCall }>(path, { method: 'POST', body: JSON.stringify(input) })
      setData((current) => ({ ...current, pending: result.pending }))
      setView('home')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '保存できませんでした。')
    } finally {
      setBusy(false)
    }
  }

  const submitProfile = async (input: FirstRunProfileInput) => {
    setBusy(true)
    setError('')
    try {
      if (PUBLIC_DEMO) {
        if (!input.own_number_confirmed || !input.future_calls_authorized) {
          throw new Error('デモの確認項目に同意してください。')
        }
        const nextProfile: ProfileStatus = { completed: true, language: input.language, phone_registered: true }
        setProfile(nextProfile)
        persistPublicDemoState(nextProfile, data)
        setView('home')
        return
      }
      const result = await api<ProfileStatus>('/api/profile', { method: 'POST', body: JSON.stringify(input) })
      setProfile(result)
      setView('home')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Profile registration failed.')
    } finally {
      setBusy(false)
    }
  }

  const cancelReservation = async () => {
    if (!window.confirm(PUBLIC_DEMO ? 'このデモ予約をキャンセルしますか？' : '未来に置いたこの電話をキャンセルしますか？')) return
    setBusy(true)
    setError('')
    try {
      if (PUBLIC_DEMO) {
        const nextData = { ...data, pending: null }
        setData(nextData)
        persistPublicDemoState(profile || DEFAULT_DEMO_STATE.profile, nextData)
        return
      }
      await api('/api/calls', { method: 'DELETE' })
      setData((current) => ({ ...current, pending: null }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'キャンセルできませんでした。')
    } finally {
      setBusy(false)
    }
  }

  const pendingDate = data.pending ? new Date(data.pending.scheduled_for) : null
  const visibleHistory = data.history.filter((item) => typeof item.content === 'string' && item.content.trim().length > 0)
  const deliveryNeedsAttention = data.pending?.delivery?.state === 'indeterminate' || data.pending?.delivery?.state === 'synchronizing'

  if (loading) {
    return <><PublicDemoNotice /><main className={`ocean-page${PUBLIC_DEMO ? ' public-demo-mode' : ''}`}><div className="loading-water">Later, Me.をたしかめています…</div></main></>
  }
  if (profile && !profile.completed) {
    return <><PublicDemoNotice /><Onboarding busy={busy} error={error} onSubmit={submitProfile} publicDemo={PUBLIC_DEMO} /></>
  }
  if (!profile) {
    return <><PublicDemoNotice /><main className={`ocean-page${PUBLIC_DEMO ? ' public-demo-mode' : ''}`}><div className="loading-water" role="alert">{error || 'Protected profile status is unavailable.'}</div></main></>
  }

  return <><PublicDemoNotice /><main className={`ocean-page${PUBLIC_DEMO ? ' public-demo-mode' : ''}`}><div className="app-shell"><aside className="sidebar"><button className="brand" onClick={() => setView('home')}><strong>Later, Me.</strong><small>Powered by CALL-E</small></button><nav aria-label="メインナビゲーション"><button className={view !== 'history' ? 'active' : ''} onClick={() => setView('home')}><span>⌂</span> ホーム</button><button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}><span>≋</span> これまで</button></nav><div className="side-plant" aria-hidden="true">〽</div><p className="side-script">for me,<br />later</p></aside>
    <section className="content">{(view === 'create' || view === 'change') ? <CreateCallPreview mode={view} initialDate={pendingDate} busy={busy} error={error} onCancel={() => { setError(''); setView('home') }} onSubmit={submitReservation} publicDemo={PUBLIC_DEMO} /> : view === 'history' ? <section className="history-view quiet-history"><header className="view-heading quiet-heading"><h1>これまで</h1><p className="completed-call-count">{data.completed_call_count}回</p></header>{visibleHistory.length ? <div className="history-list quiet-history-list">{visibleHistory.map((item, index) => { const when = item.occurred_at ? new Date(item.occurred_at) : null; return <article className="history-card quiet-history-card" key={`${item.occurred_at}-${index}`}><div className="history-light" /><div>{item.demo_sample && <p className="demo-sample-label">DEMO SAMPLE · RELATIONSHIP TRACE</p>}{when && <p className="eyebrow">{dateFormat.format(when)} {timeFormat.format(when)}</p>}<p className="trace-copy">{item.content}</p></div></article> })}</div> : <div className="empty-history quiet-empty-history"><h2>まだ、残しておくものはありません。</h2></div>}</section> : <section className="home-view quiet-home"><header className="home-heading quiet-heading"><p className="eyebrow">{data.pending ? 'WAITING FOR YOU' : 'FOR LATER'}</p><h1>{data.pending ? 'Next Call' : 'Later, Me.'}</h1><p className="future-care-line">少し先のあなたを、気にかけておく。</p></header>{data.pending && pendingDate ? <div className="home-grid quiet-home-grid"><section className="next-card quiet-water-card"><p className="section-label">次の電話</p><h2>{dateFormat.format(pendingDate)}</h2><time>{timeFormat.format(pendingDate)}</time><p className="countdown">{countdown(pendingDate, now)}</p>{data.pending.future_message && <p className="saved-message">「{data.pending.future_message}」</p>}{deliveryNeedsAttention && <p className="delivery-warning" role="alert">配信予定との同期を確認できません。予約サービスの案内を確認してください。</p>}<div className="card-actions"><button className="primary-button" onClick={() => setView('change')}>変更する</button><button className="danger-button" disabled={busy} onClick={cancelReservation}>キャンセルする</button></div></section></div> : <div className="empty-home quiet-empty-home"><section className="empty-water-card"><div className="empty-water-content"><p className="quiet-range">4時間後から10年先まで</p><button className="primary-button" onClick={() => setView('create')}>未来の電話を置く</button></div></section></div>}{error && <p className="connection-error" role="alert">{error}</p>}<button className="history-peek quiet-history-peek" onClick={() => setView('history')}><span>≋</span><strong>これまで</strong><small>{data.completed_call_count}回</small></button></section>}</section></div></main></>
}

export default App
