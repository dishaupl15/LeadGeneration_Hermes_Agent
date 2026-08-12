/**
 * PublicForm.jsx
 * ──────────────
 * Public-facing form page at /f/:form_id
 * No CRM login required.
 * Reads source + campaign_id from URL query params.
 */

import { useState, useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getPublicForm, submitPublicForm } from '../services/api'

const PLATFORM_LABELS = {
  linkedin:  { label: 'LinkedIn',   icon: '💼', color: 'text-sky-600' },
  x:         { label: 'X/Twitter',  icon: '𝕏',  color: 'text-slate-700' },
  whatsapp:  { label: 'WhatsApp',   icon: '💬', color: 'text-green-600' },
  facebook:  { label: 'Facebook',   icon: '👥', color: 'text-blue-600' },
  website:   { label: 'Website',    icon: '🌐', color: 'text-indigo-600' },
  other:     { label: 'Other',      icon: '🔗', color: 'text-slate-500' },
}

/* ── form field component ──────────────────────────────────────────────────── */
function FormField({ question, value, onChange, error }) {
  const { label, type, required, options, placeholder } = question
  const id = `field-${question.question_id}`

  const inputClass = `w-full rounded-xl border px-4 py-2.5 text-sm text-slate-900
    placeholder-slate-400 focus:outline-none focus:ring-2 transition-all
    ${error
      ? 'border-rose-300 focus:ring-rose-400 bg-rose-50'
      : 'border-slate-300 focus:ring-indigo-500 focus:border-indigo-500 bg-white'}`

  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-semibold text-slate-700">
        {label}
        {required && <span className="text-rose-500 ml-1">*</span>}
      </label>

      {type === 'short_text' && (
        <input id={id} type="text" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''} className={inputClass} />
      )}

      {type === 'email' && (
        <input id={id} type="email" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || 'you@example.com'} className={inputClass} />
      )}

      {type === 'phone' && (
        <input id={id} type="tel" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || '+91 9876543210'} className={inputClass} />
      )}

      {type === 'number' && (
        <input id={id} type="number" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''} className={inputClass} />
      )}

      {type === 'long_text' && (
        <textarea id={id} value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''} rows={4}
          className={`${inputClass} resize-none`} />
      )}

      {type === 'dropdown' && (
        <div className="relative">
          <select id={id} value={value || ''} onChange={e => onChange(e.target.value)}
            className={`${inputClass} pr-9 appearance-none`}>
            <option value="">— Select —</option>
            {(options || []).map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
            <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
            </svg>
          </div>
        </div>
      )}

      {type === 'radio' && (
        <div className="flex flex-col gap-2 mt-0.5">
          {(options || []).map(o => (
            <label key={o.value} className="flex items-center gap-3 cursor-pointer group">
              <input type="radio" name={id} value={o.value} checked={value === o.value}
                onChange={() => onChange(o.value)}
                className="w-4 h-4 text-indigo-600 border-slate-300 focus:ring-indigo-500" />
              <span className="text-sm text-slate-700 group-hover:text-slate-900">{o.label}</span>
            </label>
          ))}
        </div>
      )}

      {type === 'checkbox' && (
        <div className="flex flex-col gap-2 mt-0.5">
          {(options || []).map(o => {
            const checked = Array.isArray(value) ? value.includes(o.value) : false
            const toggle = () => {
              const cur = Array.isArray(value) ? value : []
              onChange(checked ? cur.filter(v => v !== o.value) : [...cur, o.value])
            }
            return (
              <label key={o.value} className="flex items-center gap-3 cursor-pointer group">
                <input type="checkbox" checked={checked} onChange={toggle}
                  className="w-4 h-4 text-indigo-600 rounded border-slate-300 focus:ring-indigo-500" />
                <span className="text-sm text-slate-700 group-hover:text-slate-900">{o.label}</span>
              </label>
            )
          })}
        </div>
      )}

      {error && <p className="text-xs text-rose-500 flex items-center gap-1 mt-0.5">
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
            d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
        </svg>
        {error}
      </p>}
    </div>
  )
}

/* ── main public form page ─────────────────────────────────────────────────── */
export default function PublicForm() {
  const { form_id }       = useParams()
  const [searchParams]    = useSearchParams()

  // Read tracking params from URL — these are set server-side and cannot be tampered
  const source      = searchParams.get('source')      || 'other'
  const campaign_id = searchParams.get('campaign_id') || searchParams.get('campaign') || null

  const [form,      setForm]      = useState(null)
  const [loading,   setLoading]   = useState(true)
  const [notFound,  setNotFound]  = useState(false)
  const [answers,   setAnswers]   = useState({})   // { question_id: value }
  const [errors,    setErrors]    = useState({})
  const [submitting,setSubmitting]= useState(false)
  const [submitted, setSubmitted] = useState(false)
  const [submitErr, setSubmitErr] = useState(null)

  useEffect(() => {
    getPublicForm(form_id)
      .then(d => setForm(d.form))
      .catch(() => setNotFound(true))
      .finally(() => setLoading(false))
  }, [form_id])

  const setAnswer = (qid, val) => {
    setAnswers(prev => ({ ...prev, [qid]: val }))
    setErrors(prev => { const e = { ...prev }; delete e[qid]; return e })
  }

  const validate = () => {
    const newErrors = {}
    for (const q of (form?.questions || [])) {
      const val = answers[q.question_id]
      if (q.required) {
        const isEmpty = val === undefined || val === null || val === '' ||
          (Array.isArray(val) && val.length === 0)
        if (isEmpty) {
          newErrors[q.question_id] = `${q.label} is required`
        }
      }
      if (q.type === 'email' && val) {
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(val).trim())) {
          newErrors[q.question_id] = 'Please enter a valid email address'
        }
      }
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setSubmitErr(null)
    if (!validate()) return

    const answerList = Object.entries(answers)
      .filter(([, v]) => v !== undefined && v !== '' && !(Array.isArray(v) && v.length === 0))
      .map(([question_id, value]) => ({ question_id, value }))

    setSubmitting(true)
    try {
      await submitPublicForm(form_id, {
        answers:     answerList,
        source:      source,
        campaign_id: campaign_id,
      })
      setSubmitted(true)
    } catch (err) {
      setSubmitErr(err.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  /* ── loading ─────────────────────────────────────────────────────────────── */
  if (loading) return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 to-slate-100 flex items-center justify-center">
      <svg className="w-10 h-10 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
      </svg>
    </div>
  )

  /* ── not found / inactive ────────────────────────────────────────────────── */
  if (notFound || !form) return (
    <div className="min-h-screen bg-gradient-to-br from-slate-50 to-slate-100 flex items-center justify-center px-4">
      <div className="text-center max-w-sm">
        <div className="w-16 h-16 rounded-2xl bg-rose-100 flex items-center justify-center mx-auto mb-4">
          <svg className="w-8 h-8 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <h1 className="text-xl font-bold text-slate-800 mb-2">Form Not Found</h1>
        <p className="text-sm text-slate-500">This form may have been removed or is no longer active.</p>
      </div>
    </div>
  )

  /* ── success ─────────────────────────────────────────────────────────────── */
  if (submitted) return (
    <div className="min-h-screen bg-gradient-to-br from-emerald-50 to-teal-50 flex items-center justify-center px-4">
      <div className="text-center max-w-sm w-full bg-white rounded-3xl shadow-xl p-8">
        <div className="w-16 h-16 rounded-full bg-emerald-100 flex items-center justify-center mx-auto mb-5">
          <svg className="w-8 h-8 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
          </svg>
        </div>
        <h1 className="text-2xl font-bold text-slate-900 mb-2">Thank you!</h1>
        <p className="text-sm text-slate-500 mb-1">Your details have been submitted successfully.</p>
        <p className="text-xs text-slate-400">We'll be in touch with you soon.</p>
      </div>
    </div>
  )

  /* ── form ────────────────────────────────────────────────────────────────── */
  const plt = PLATFORM_LABELS[source] ?? PLATFORM_LABELS.other
  const sortedQuestions = [...(form.questions || [])].sort((a, b) => a.display_order - b.display_order)

  return (
    <div className="min-h-screen bg-gradient-to-br from-indigo-50 via-white to-slate-50 py-8 px-4">
      <div className="max-w-lg mx-auto">

        {/* Source badge */}
        {source && source !== 'other' && (
          <div className={`inline-flex items-center gap-1.5 text-xs font-semibold mb-4 ${plt.color}`}>
            <span>{plt.icon}</span>
            <span>Via {plt.label}</span>
          </div>
        )}

        {/* Form card */}
        <div className="bg-white rounded-3xl shadow-xl overflow-hidden">
          {/* Header gradient */}
          <div className="bg-gradient-to-r from-indigo-600 to-violet-600 px-8 py-7">
            <h1 className="text-xl font-bold text-white leading-snug">{form.name}</h1>
            {form.description && (
              <p className="text-sm text-indigo-200 mt-2 leading-relaxed">{form.description}</p>
            )}
            <div className="mt-3 inline-flex items-center gap-1.5 text-xs text-indigo-300">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M19 21V5a2 2 0 00-2-2H7a2 2 0 00-2 2v16m14 0h2m-2 0h-5m-9 0H3m2 0h5"/>
              </svg>
              {form.category}
            </div>
          </div>

          {/* Questions */}
          <form onSubmit={handleSubmit} className="px-8 py-7 space-y-6">

            {submitErr && (
              <div className="p-3 rounded-xl bg-rose-50 border border-rose-200 text-sm text-rose-700 flex items-center gap-2">
                <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                    d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                </svg>
                {submitErr}
              </div>
            )}

            {sortedQuestions.map(q => (
              <FormField
                key={q.question_id}
                question={q}
                value={answers[q.question_id]}
                onChange={val => setAnswer(q.question_id, val)}
                error={errors[q.question_id]}
              />
            ))}

            {/* Honeypot — hidden from real users */}
            <input type="text" name="hp" autoComplete="off"
              className="absolute left-[-9999px] opacity-0 pointer-events-none"
              tabIndex={-1} aria-hidden="true" />

            <button type="submit" disabled={submitting}
              className="w-full py-3.5 rounded-2xl text-base font-bold text-white
                         bg-gradient-to-r from-indigo-600 to-violet-600
                         hover:from-indigo-700 hover:to-violet-700
                         shadow-md hover:shadow-lg transition-all
                         disabled:opacity-60 disabled:cursor-not-allowed
                         flex items-center justify-center gap-2.5">
              {submitting ? (
                <>
                  <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                  </svg>
                  Submitting…
                </>
              ) : (
                <>
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                      d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8"/>
                  </svg>
                  Submit
                </>
              )}
            </button>

            <p className="text-center text-xs text-slate-400 mt-2">
              Your information is secure and will not be shared.
            </p>
          </form>
        </div>

        <p className="text-center text-[11px] text-slate-400 mt-4">
          Powered by LeadCRM
        </p>
      </div>
    </div>
  )
}
