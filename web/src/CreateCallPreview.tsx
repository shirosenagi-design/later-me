import { useEffect, useMemo, useState, type FormEvent } from 'react'
import type { ProfileLanguage } from './Onboarding'

export type ReservationInput = { scheduled_for: string; future_message: string; timezone?: string }
type Props = { initialDate?: Date | null; mode: 'create' | 'change'; language: ProfileLanguage; busy: boolean; error: string; maxDateIso?: string | null; onCancel: () => void; onSubmit: (value: ReservationInput) => Promise<void> }
type RuntimeStatus = { booking_minimum_minutes?: number; dev_short_horizon_enabled?: boolean }
const pad = (value: number) => String(value).padStart(2, '0')
const dateValue = (date: Date) => `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
const timeValue = (date: Date) => `${pad(date.getHours())}:${pad(date.getMinutes())}`

const copy = {
  en: {
    careLine: 'Take care of your future self, just a little further ahead.',
    createHeading: 'When should your future self call?',
    changeHeading: 'When should we move it to?',
    developmentMinimum: (minutes: number) => `Live development check: at least ${minutes} minutes from now`,
    normalMinimum: 'At least 4 hours from now',
    publicMaximum: 'Within this limited public trial window',
    normalMaximum: 'Up to 10 years from now',
    oneAtATime: 'You can reserve one future call at a time.',
    rangeError: 'Choose a time within the available reservation window.',
    messageLabel: 'Leave something for your future self?',
    messagePlaceholder: 'Optional. Leave a line that can become the starting point for your future call.',
    saving: 'Placing it…',
    changeSubmit: 'Save this new time',
    createSubmit: 'Schedule this call',
    back: 'Back',
    now: 'Now',
    futureYou: 'Future self',
    nowSmall: 'Present',
    futureSmall: 'Future me',
  },
  ja: {
    careLine: '少し先のあなたを、気にかけておく。',
    createHeading: 'いつ、会いに来てもらう？',
    changeHeading: 'いつに、置きなおす？',
    developmentMinimum: (minutes: number) => `開発ライブ確認：最短${minutes}分後から`,
    normalMinimum: '最短4時間後から',
    publicMaximum: 'この期間限定公開で配信できる日時まで',
    normalMaximum: '最大10年先まで',
    oneAtATime: '予約できる電話は、一度に一本だけ。',
    rangeError: '利用できる予約期間内の時間を選んでください。',
    messageLabel: '未来の自分へ、何か残しておく？',
    messagePlaceholder: '空欄でも大丈夫。未来の電話のきっかけになる一言を。',
    saving: '置いています…',
    changeSubmit: 'この時間に置きなおす',
    createSubmit: 'この時間に置いておく',
    back: '戻る',
    now: 'いま',
    futureYou: '未来のあなた',
    nowSmall: 'Now',
    futureSmall: 'Future me',
  },
} as const

export default function CreateCallPreview({ initialDate, mode, language, busy, error, maxDateIso, onCancel, onSubmit }: Props) {
  const [runtime, setRuntime] = useState({ minimumMinutes: 240, developmentShortHorizon: false })
  const { minimumMinutes, developmentShortHorizon } = runtime
  const text = copy[language]
  // Limits intentionally snapshot when the form opens; the Python service validates again on submit.
  // oxlint-disable-next-line react/purity
  const limits = useMemo(() => {
    const min = new Date(Date.now() + minimumMinutes * 60 * 1000)
    min.setSeconds(0, 0)
    min.setMinutes(min.getMinutes() + 1)
    const max = new Date()
    max.setFullYear(max.getFullYear() + 10)
    if (maxDateIso) {
      const publicMax = new Date(maxDateIso)
      if (Number.isFinite(publicMax.getTime()) && publicMax < max) return { min, max: publicMax }
    }
    return { min, max }
  }, [minimumMinutes, maxDateIso])
  const seed = initialDate && initialDate > limits.min ? initialDate : limits.min
  const [date, setDate] = useState(dateValue(seed)); const [time, setTime] = useState(timeValue(seed)); const [message, setMessage] = useState('')
  useEffect(() => { let active = true; void fetch('/api/health', { headers: { Accept: 'application/json' } }).then((response) => response.json() as Promise<RuntimeStatus>).then((health) => { if (!active || health.dev_short_horizon_enabled !== true || health.booking_minimum_minutes !== 5) return; setRuntime({ minimumMinutes: health.booking_minimum_minutes, developmentShortHorizon: true }); if (mode === 'create' && !initialDate) { const shortMinimum = new Date(Date.now() + health.booking_minimum_minutes * 60 * 1000); shortMinimum.setSeconds(0, 0); shortMinimum.setMinutes(shortMinimum.getMinutes() + 1); setDate(dateValue(shortMinimum)); setTime(timeValue(shortMinimum)) } }).catch(() => undefined); return () => { active = false } }, [initialDate, mode])
  const selected = new Date(`${date}T${time}`); const valid = Number.isFinite(selected.getTime()) && selected >= limits.min && selected <= limits.max
  const submit = async (event: FormEvent) => { event.preventDefault(); if (valid && !busy) await onSubmit({ scheduled_for: `${date} ${time}`, future_message: message, timezone: Intl.DateTimeFormat().resolvedOptions().timeZone }) }
  return <section className="form-view" aria-labelledby="future-call-title">
    <header className="view-heading"><p className="eyebrow">PLACE A FUTURE CALL</p><h1 id="future-call-title">Later, Me.</h1><p>{text.careLine}</p></header>
    <div className="form-story-grid"><form className="ocean-form" onSubmit={submit}>
      <h2>{mode === 'change' ? text.changeHeading : text.createHeading}</h2>
      <div className="date-time-row"><label><span>DATE</span><input type="date" value={date} min={dateValue(limits.min)} max={dateValue(limits.max)} onInput={(e) => setDate(e.currentTarget.value)} required /></label><label><span>TIME</span><input type="time" value={time} onInput={(e) => setTime(e.currentTarget.value)} required /></label></div>
      <ul className="rules"><li>{developmentShortHorizon ? text.developmentMinimum(minimumMinutes) : text.normalMinimum}</li><li>{maxDateIso ? text.publicMaximum : text.normalMaximum}</li><li>{text.oneAtATime}</li></ul>
      {!valid && <p className="range-error" role="status">{text.rangeError}</p>}
      {mode === 'create' && <label className="message-field"><span>{text.messageLabel}</span><textarea value={message} maxLength={500} placeholder={text.messagePlaceholder} onChange={(e) => setMessage(e.target.value)} /><small>{message.length} / 500</small></label>}
      {error && <p className="form-error" role="alert">{error}</p>}<div className="form-actions"><button className="primary-button" type="submit" disabled={!valid || busy}>{busy ? text.saving : mode === 'change' ? text.changeSubmit : text.createSubmit}</button><button className="quiet-button" type="button" onClick={onCancel}>{text.back}</button></div>
    </form><div className="story-path" aria-hidden="true"><div className="story-orb now-orb">{text.now}<small>{text.nowSmall}</small></div><div className="dotted-current" /><span className="tiny-fish">› › ›</span><div className="story-orb future-orb">{text.futureYou}<small>{text.futureSmall}</small></div></div></div>
  </section>
}
