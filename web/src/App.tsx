import { useCallback, useEffect, useMemo, useState } from 'react'
import './App.css'
import CreateCallPreview, { type ReservationInput } from './CreateCallPreview'
import Onboarding, { type FirstRunProfileInput, type ProfileLanguage } from './Onboarding'

type DeliveryState = { state?: string; coherent?: boolean; mode?: string; error_code?: string | null }
type PendingCall = { status: string; scheduled_for: string; created_at?: string; updated_at?: string; future_message?: string | null; delivery?: DeliveryState | null }
type HistoryItem = { occurred_at?: string | null; scheduled_for?: string | null; status?: string | null; call_status?: string | null; delivery_outcome?: string | null; future_message?: string | null; summary?: string | null; trace?: string | null; failure?: string | null; content?: string | null }
type TrialState = { max_calls?: number; reserved_calls?: number; consumed_calls?: number; slots_remaining?: number; enabled?: boolean; accepting_reservations?: boolean; booking_close_at?: string | null; dispatch_end_at?: string | null; real_calls?: boolean }
type ProfileStatus = { completed: boolean; language: ProfileLanguage | null; phone_registered: boolean }
type AppState = { pending: PendingCall | null; history: HistoryItem[]; completed_call_count: number; trial?: TrialState }
type View = 'home' | 'create' | 'change' | 'history'

const publicLive = import.meta.env.VITE_PUBLIC_LIVE === 'true'

const copy = {
  en: {
    checking: 'Checking Later, Me.…',
    publicConnectionError: 'The public booking service is unavailable. Please wait a moment and reload.',
    localConnectionError: 'The local booking service is unavailable. Start the Python API and try again.',
    saveError: 'Could not save the reservation.',
    cancelError: 'Could not cancel the reservation.',
    cancelConfirm: 'Cancel this future call?',
    navLabel: 'Main navigation',
    home: 'Home',
    history: 'Past Calls',
    historyHeading: 'Past Calls',
    emptyHistory: 'No call history yet.',
    callsUnit: (count: number) => `${count} ${count === 1 ? 'call' : 'calls'}`,
    careLine: 'Take care of your future self, just a little further ahead.',
    nextCall: 'Next call',
    waitingSoon: 'It is almost time for your call.',
    countdown: (days: number, hours: number, minutes: number) => `in ${days ? `${days}d ` : ''}${hours ? `${hours}h ` : ''}${minutes}m`,
    dispatching: 'It is time. CALL-E is processing this real call.',
    deliveryNeedsAttention: 'Checking delivery status. The same call will not be redialed automatically.',
    change: 'Change',
    cancel: 'Cancel',
    publicRange: 'From 4 hours from now until the end of this limited public trial',
    normalRange: 'From 4 hours ahead up to 10 years',
    trialFull: 'The limited real CALL-E call capacity has been reached.',
    trialClosed: 'New reservations for this limited public trial are closed.',
    placeCall: 'Place a future call',
    pastMe: 'Past me',
  },
  ja: {
    checking: 'Later, Me.をたしかめています…',
    publicConnectionError: '公開予約サービスに接続できません。少し待ってから再読み込みしてください。',
    localConnectionError: 'ローカルの予約サービスに接続できません。Python APIを起動してください。',
    saveError: '保存できませんでした。',
    cancelError: 'キャンセルできませんでした。',
    cancelConfirm: '未来に置いたこの電話をキャンセルしますか？',
    navLabel: 'メインナビゲーション',
    home: 'ホーム',
    history: 'これまで',
    historyHeading: 'これまで',
    emptyHistory: 'まだ、電話の履歴はありません。',
    callsUnit: (count: number) => `${count}回`,
    careLine: '少し先のあなたを、気にかけておく。',
    nextCall: '次の電話',
    waitingSoon: 'そろそろ、電話の時間。',
    countdown: (days: number, hours: number, minutes: number) => `あと ${days ? `${days}日 ` : ''}${hours ? `${hours}時間 ` : ''}${minutes}分`,
    dispatching: '予約時刻になりました。CALL-Eがこの実通話を処理しています。',
    deliveryNeedsAttention: '配信状態を確認中です。自動で同じ電話を再発信することはありません。',
    change: '変更する',
    cancel: 'キャンセルする',
    publicRange: '4時間後から、この期間限定公開で配信できる日時まで',
    normalRange: '4時間後から10年先まで',
    trialFull: '期間限定の実CALL-E通話枠は上限に達しました。',
    trialClosed: 'この期間限定公開の新規予約受付は終了しました。',
    placeCall: '未来の電話を置く',
    pastMe: 'Past me',
  },
} as const

function countdown(target: Date, now: Date, language: ProfileLanguage) {
  const total = Math.max(0, Math.ceil((target.getTime() - now.getTime()) / 60000))
  const days = Math.floor(total / 1440)
  const hours = Math.floor((total % 1440) / 60)
  const minutes = total % 60
  return total === 0 ? copy[language].waitingSoon : copy[language].countdown(days, hours, minutes)
}

const qaInstanceId = import.meta.env.VITE_CALL_E_QA_INSTANCE_ID?.trim()
async function isolatedQaHeaders(init?: RequestInit): Promise<Record<string, string>> {
  const method = (init?.method || 'GET').toUpperCase()
  if (!qaInstanceId || method === 'GET') return {}
  const response = await fetch('/api/health', { headers: { Accept: 'application/json' } })
  const health = await response.json()
  if (!response.ok || health.storage_mode !== 'isolated' || health.instance_id !== qaInstanceId || health.dispatch_enabled !== false) throw new Error('The isolated QA booking service could not be verified. Nothing was saved.')
  return { 'X-CALL-E-QA-Instance': qaInstanceId }
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const qaHeaders = await isolatedQaHeaders(init)
  const response = await fetch(path, { ...init, headers: { 'Content-Type': 'application/json', ...qaHeaders, ...init?.headers } })
  const body = await response.json()
  if (!response.ok) throw new Error(body.error || body.detail || 'Request failed.')
  return body as T
}

function historyStatusLabel(item: HistoryItem) {
  if (item.status === 'completed') return 'CALL COMPLETED'
  if (item.status === 'failed') return 'CALL ATTEMPT FAILED'
  if (item.status === 'canceled') return 'CANCELED'
  return (item.status || 'CALL').toUpperCase()
}

function App() {
  const [data, setData] = useState<AppState>({ pending: null, history: [], completed_call_count: 0 })
  const [profile, setProfile] = useState<ProfileStatus | null>(null)
  const [view, setView] = useState<View>('home')
  const [now, setNow] = useState(new Date())
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const language: ProfileLanguage = profile?.language === 'en' ? 'en' : 'ja'
  const text = copy[language]
  const dateFormat = useMemo(() => new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'ja-JP', { year: 'numeric', month: 'long', day: 'numeric', weekday: 'short' }), [language])
  const timeFormat = useMemo(() => new Intl.DateTimeFormat(language === 'en' ? 'en-US' : 'ja-JP', { hour: '2-digit', minute: '2-digit', hour12: false }), [language])

  const refresh = useCallback(async () => {
    try {
      // Profile is intentionally fetched first. On a first public visit it creates
      // the HttpOnly session cookie; the following state request must use that same session.
      const nextProfile = await api<ProfileStatus>('/api/profile')
      const nextData = await api<AppState>('/api/state')
      setData(nextData)
      setProfile(nextProfile)
      setError('')
    } catch {
      setError(publicLive ? 'Public booking service unavailable / 公開予約サービスに接続できません。' : 'Local booking service unavailable / ローカル予約サービスに接続できません。')
    } finally {
      setLoading(false)
    }
  }, [])

  // Polling synchronizes React with the active booking store.
  // oxlint-disable-next-line react/set-state-in-effect
  useEffect(() => { void refresh(); const poll = window.setInterval(refresh, 30000); return () => window.clearInterval(poll) }, [refresh])
  useEffect(() => { const timer = window.setInterval(() => setNow(new Date()), 1000); return () => window.clearInterval(timer) }, [])

  const submitReservation = async (input: ReservationInput) => {
    setBusy(true); setError('')
    try {
      const path = view === 'change' ? '/api/calls/change' : '/api/calls'
      const result = await api<{ pending: PendingCall; trial?: TrialState }>(path, { method: 'POST', body: JSON.stringify(input) })
      setData((current) => ({ ...current, pending: result.pending, trial: result.trial || current.trial }))
      setView('home')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.saveError)
    } finally { setBusy(false) }
  }

  const submitProfile = async (input: FirstRunProfileInput) => {
    setBusy(true); setError('')
    try {
      const result = await api<ProfileStatus>('/api/profile', { method: 'POST', body: JSON.stringify(input) })
      setProfile(result)
      setView('home')
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : 'Profile registration failed.')
    } finally { setBusy(false) }
  }

  const cancelReservation = async () => {
    if (!window.confirm(text.cancelConfirm)) return
    setBusy(true); setError('')
    try {
      const result = await api<{ pending: null; trial?: TrialState }>('/api/calls', { method: 'DELETE' })
      setData((current) => ({ ...current, pending: null, trial: result.trial || current.trial }))
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : text.cancelError)
    } finally { setBusy(false) }
  }

  const pendingDate = data.pending ? new Date(data.pending.scheduled_for) : null
  const visibleHistory = data.history
  const deliveryNeedsAttention = data.pending?.delivery?.state === 'indeterminate' || data.pending?.delivery?.state === 'synchronizing'
  const dispatching = data.pending?.status === 'dispatching'
  const trialFull = publicLive && data.trial?.accepting_reservations === false && (data.trial?.slots_remaining ?? 0) <= 0
  const trialClosed = publicLive && data.trial?.accepting_reservations === false && !trialFull
  const trialLabel = publicLive ? `HACKATHON LIMITED TRIAL · REAL CALL-E CALLS${typeof data.trial?.slots_remaining === 'number' ? ` · ${data.trial.slots_remaining} slots left` : ''}` : null

  if (loading) return <main className="ocean-page"><div className="loading-water">{text.checking}</div></main>
  if (!loading && profile && !profile.completed) return <Onboarding busy={busy} error={error} onSubmit={submitProfile} />
  if (!loading && !profile) return <main className="ocean-page"><div className="loading-water" role="alert">{error || 'Protected profile status is unavailable.'}</div></main>

  return <main className="ocean-page"><div className="app-shell"><aside className="sidebar"><button className="brand" onClick={() => setView('home')}><strong>Later, Me.</strong><small>Powered by CALL-E</small></button><nav aria-label={text.navLabel}><button className={view !== 'history' ? 'active' : ''} onClick={() => setView('home')}><span>⌂</span> {text.home}</button><button className={view === 'history' ? 'active' : ''} onClick={() => setView('history')}><span>≋</span> {text.history}</button></nav><div className="side-plant" aria-hidden="true">〽</div><p className="side-script">for me,<br />later</p></aside>
    <section className="content">{(view === 'create' || view === 'change') ? <CreateCallPreview mode={view} language={language} initialDate={pendingDate} maxDateIso={publicLive ? data.trial?.dispatch_end_at : null} busy={busy} error={error} onCancel={() => { setError(''); setView('home') }} onSubmit={submitReservation} /> : view === 'history' ? <section className="history-view quiet-history"><header className="view-heading quiet-heading">{trialLabel && <p className="eyebrow">{trialLabel}</p>}<h1>{text.historyHeading}</h1><p className="completed-call-count">{text.callsUnit(data.completed_call_count)}</p></header>{visibleHistory.length ? <div className="history-list quiet-history-list">{visibleHistory.map((item, index) => { const when = item.occurred_at ? new Date(item.occurred_at) : null; return <article className="history-card quiet-history-card" key={`${item.occurred_at}-${index}`}><div className="history-light" /><div>{when && <p className="eyebrow">{dateFormat.format(when)} {timeFormat.format(when)} · {historyStatusLabel(item)}</p>}{item.trace && <p className="trace-copy">{item.trace}</p>}{!item.trace && item.summary && <p className="trace-copy">{item.summary}</p>}{item.future_message && <p className="saved-message">{text.pastMe}: 「{item.future_message}」</p>}{item.failure && <p className="delivery-warning" role="status">{item.failure}</p>}</div></article> })}</div> : <div className="empty-history quiet-empty-history"><h2>{text.emptyHistory}</h2></div>}</section> : <section className="home-view quiet-home"><header className="home-heading quiet-heading"><p className="eyebrow">{trialLabel || (data.pending ? 'WAITING FOR YOU' : 'FOR LATER')}</p><h1>{data.pending ? 'Next Call' : 'Later, Me.'}</h1><p className="future-care-line">{text.careLine}</p></header>{data.pending && pendingDate ? <div className="home-grid quiet-home-grid"><section className="next-card quiet-water-card"><p className="section-label">{text.nextCall}</p><h2>{dateFormat.format(pendingDate)}</h2><time>{timeFormat.format(pendingDate)}</time><p className="countdown">{countdown(pendingDate, now, language)}</p>{data.pending.future_message && <p className="saved-message">「{data.pending.future_message}」</p>}{dispatching && <p className="delivery-warning" role="status">{text.dispatching}</p>}{deliveryNeedsAttention && <p className="delivery-warning" role="alert">{text.deliveryNeedsAttention}</p>}{!dispatching && <div className="card-actions"><button className="primary-button" onClick={() => setView('change')}>{text.change}</button><button className="danger-button" disabled={busy} onClick={cancelReservation}>{text.cancel}</button></div>}</section></div> : <div className="empty-home quiet-empty-home"><section className="empty-water-card"><div className="empty-water-content"><p className="quiet-range">{publicLive ? text.publicRange : text.normalRange}</p>{trialFull ? <p className="delivery-warning" role="status">{text.trialFull}</p> : trialClosed ? <p className="delivery-warning" role="status">{text.trialClosed}</p> : <button className="primary-button" onClick={() => setView('create')}>{text.placeCall}</button>}</div></section></div>}{error && <p className="connection-error" role="alert">{error}</p>}<button className="history-peek quiet-history-peek" onClick={() => setView('history')}><span>≋</span><strong>{text.history}</strong><small>{text.callsUnit(data.completed_call_count)}</small></button></section>}</section></div></main>
}
export default App
