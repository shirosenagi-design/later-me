import { useState, type FormEvent } from 'react'

export type ProfileLanguage = 'en' | 'ja'

export type FirstRunProfileInput = {
  language: ProfileLanguage
  phone: string
  own_number_confirmed: boolean
  future_calls_authorized: boolean
}

type Props = {
  busy: boolean
  error: string
  onSubmit: (input: FirstRunProfileInput) => Promise<void>
  publicDemo?: boolean
}

const DEMO_PHONE = '+819012345678'

const copy = {
  en: {
    eyebrow: 'FIRST ENCOUNTER',
    heading: 'A line to your future self',
    intro: 'Before leaving the first call in the water, tell CALL-E where it may reach you.',
    phoneLabel: 'Your phone number',
    phoneHint: 'Use international format: +, country code, then your number.',
    ownNumber: 'I confirm that this is my own phone number.',
    permission: 'CALL-E may call this number only for future calls that I schedule myself.',
    privacy: 'Your number stays in protected local server storage and is used only for your scheduled future calls.',
    submit: 'Enter Ocean',
  },
  ja: {
    eyebrow: 'はじめての出会い',
    heading: '未来のあなたへ、線をひく。',
    intro: '最初の電話を海に置く前に、CALL-Eがあなたへ届く場所を教えてください。',
    phoneLabel: 'あなた自身の電話番号',
    phoneHint: '「+」「国番号」「電話番号」の国際形式で入力してください。',
    ownNumber: 'これは私自身の電話番号です。',
    permission: '私が自分で予約した未来の電話に限り、CALL-Eがこの番号へ電話することを許可します。',
    privacy: '番号はローカルサーバーの保護領域に保存され、あなた自身が予約した未来の電話にだけ使われます。',
    submit: 'Oceanへ入る',
  },
} as const

const demoCopy = {
  en: {
    eyebrow: 'INTERACTIVE DEMO',
    heading: 'A line to your future self',
    intro: 'This browser-only demo stores a fictional reservation locally. No phone call is placed.',
    phoneLabel: 'Demo phone number',
    phoneHint: 'This fictional E.164 number is used only to demonstrate onboarding.',
    ownNumber: 'I understand this is a fictional demo number and no phone call will be placed.',
    permission: 'I consent to store this demo reservation only in this browser.',
    privacy: "Demo state stays in this browser's local storage. CALL-E and OpenAI are not contacted.",
    submit: 'Enter Ocean',
  },
  ja: {
    eyebrow: 'INTERACTIVE DEMO',
    heading: '未来のあなたへ、線をひく。',
    intro: 'このブラウザだけで、架空の未来の電話を置くデモです。実際の電話は発信されません。',
    phoneLabel: 'デモ用の電話番号',
    phoneHint: 'オンボーディング確認専用の、架空のE.164番号です。',
    ownNumber: 'これは架空のデモ番号で、電話は発信されないことを確認しました。',
    permission: 'このデモ予約を、このブラウザだけに保存することに同意します。',
    privacy: 'デモ状態はブラウザのlocalStorageにだけ残ります。CALL-EとOpenAIには接続しません。',
    submit: 'Oceanへ入る',
  },
} as const

export default function Onboarding({ busy, error, onSubmit, publicDemo = false }: Props) {
  const [language, setLanguage] = useState<ProfileLanguage | null>(null)
  const [phone, setPhone] = useState(publicDemo ? DEMO_PHONE : '')
  const [ownNumberConfirmed, setOwnNumberConfirmed] = useState(false)
  const [futureCallsAuthorized, setFutureCallsAuthorized] = useState(false)
  const selectedCopy = language ? (publicDemo ? demoCopy[language] : copy[language]) : null

  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!language || !ownNumberConfirmed || !futureCallsAuthorized) return
    await onSubmit({
      language,
      phone,
      own_number_confirmed: ownNumberConfirmed,
      future_calls_authorized: futureCallsAuthorized,
    })
  }

  const ready = Boolean(
    language && phone.trim() && ownNumberConfirmed && futureCallsAuthorized,
  )

  return (
    <main className={`ocean-page onboarding-page${publicDemo ? ' public-demo-mode' : ''}`}>
      <section className="onboarding-shell" aria-labelledby="onboarding-title">
        <div className="onboarding-brand" aria-hidden="true">
          <strong>Later, Me.</strong>
          <small>Powered by CALL-E</small>
          <span>for my future me</span>
        </div>

        <div className="onboarding-content">
          <header className="onboarding-heading">
            <p className="eyebrow">FIRST RUN · はじめに</p>
            <h1 id="onboarding-title">Choose your language</h1>
            <p>ことばを選んでください。</p>
          </header>

          <div className="language-choice" role="group" aria-label="Language / 言語">
            <button
              type="button"
              className={language === 'en' ? 'language-card selected' : 'language-card'}
              aria-pressed={language === 'en'}
              onClick={() => setLanguage('en')}
            >
              <strong>English</strong>
              <small>Continue in English</small>
            </button>
            <button
              type="button"
              className={language === 'ja' ? 'language-card selected' : 'language-card'}
              aria-pressed={language === 'ja'}
              onClick={() => setLanguage('ja')}
            >
              <strong>日本語</strong>
              <small>日本語でつづける</small>
            </button>
          </div>

          {selectedCopy && (
            <form className="onboarding-form" onSubmit={submit}>
              <div className="onboarding-story-copy">
                <p className="eyebrow">{selectedCopy.eyebrow}</p>
                <h2>{selectedCopy.heading}</h2>
                <p>{selectedCopy.intro}</p>
              </div>

              <label className="onboarding-phone">
                <span>{selectedCopy.phoneLabel}</span>
                <input
                  type="tel"
                  inputMode="tel"
                  autoComplete={publicDemo ? 'off' : 'tel'}
                  value={phone}
                  onChange={(event) => setPhone(event.target.value)}
                  readOnly={publicDemo}
                  placeholder="+ country code · number"
                  required
                  aria-describedby="phone-format-hint"
                />
                <small id="phone-format-hint">{selectedCopy.phoneHint}</small>
              </label>

              <fieldset className="onboarding-confirmations">
                <legend>{language === 'en' ? 'Your consent' : '確認と同意'}</legend>
                <label>
                  <input
                    type="checkbox"
                    checked={ownNumberConfirmed}
                    onChange={(event) => setOwnNumberConfirmed(event.target.checked)}
                  />
                  <span>{selectedCopy.ownNumber}</span>
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={futureCallsAuthorized}
                    onChange={(event) => setFutureCallsAuthorized(event.target.checked)}
                  />
                  <span>{selectedCopy.permission}</span>
                </label>
              </fieldset>

              <p className="onboarding-privacy">{selectedCopy.privacy}</p>
              {error && <p className="form-error" role="alert">{error}</p>}
              <button className="primary-button onboarding-submit" disabled={!ready || busy}>
                {busy ? '…' : selectedCopy.submit}
              </button>
            </form>
          )}
        </div>

        <div className="onboarding-path" aria-hidden="true">
          <span className="onboarding-now">Now</span>
          <span className="onboarding-future">Future me</span>
        </div>
      </section>
    </main>
  )
}
