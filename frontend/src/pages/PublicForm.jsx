/**
 * PublicForm.jsx
 * ──────────────
 * Public-facing branded form page served at  /f/:form_id
 *
 * Professional layout matching the design reference:
 *   - Clean centered card on a soft gray background
 *   - Company logo + info header block (logo, name, tagline, description, contact row)
 *   - Thick rule divider
 *   - Form title block (large bold title + category badge + description + required note)
 *   - Dynamic form fields — full width, clean labels above inputs
 *   - Full-width submit button
 *   - Privacy footer
 *
 * To update branding: edit  src/config/brandConfig.js  only.
 * All submission / validation / API logic is untouched.
 */

import { useState, useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getPublicForm, submitPublicForm } from '../services/api'
import { BRAND } from '../config/brandConfig'

/* ─────────────────────────────────────────────────────────────────────────────
   Platform source badge metadata
───────────────────────────────────────────────────────────────────────────── */
const PLATFORM_LABELS = {
  linkedin: { label: 'LinkedIn',    color: 'bg-sky-50 text-sky-700 border-sky-200' },
  x:        { label: 'X / Twitter', color: 'bg-slate-50 text-slate-600 border-slate-200' },
  whatsapp: { label: 'WhatsApp',    color: 'bg-green-50 text-green-700 border-green-200' },
  facebook: { label: 'Facebook',    color: 'bg-blue-50 text-blue-700 border-blue-200' },
  website:  { label: 'Website',     color: 'bg-violet-50 text-violet-700 border-violet-200' },
  other:    { label: 'Other',       color: 'bg-slate-50 text-slate-500 border-slate-200' },
}

/* ─────────────────────────────────────────────────────────────────────────────
   Tiny SVG icons (inline — no extra deps)
───────────────────────────────────────────────────────────────────────────── */
const ic = 'w-[14px] h-[14px] flex-shrink-0'

const GlobeIcon = () => (
  <svg className={ic} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9"/>
  </svg>
)
const MailIcon = () => (
  <svg className={ic} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
  </svg>
)
const PinIcon = () => (
  <svg className={ic} fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round"
      d="M17.657 16.657L13.414 20.9a2 2 0 01-2.828 0l-4.243-4.243a8 8 0 1111.314 0z"/>
    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
  </svg>
)
const LinkedInIcon = () => (
  <svg className={ic} fill="currentColor" viewBox="0 0 24 24">
    <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
  </svg>
)
const ChevronDownIcon = () => (
  <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7"/>
  </svg>
)
const AlertIcon = () => (
  <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
  </svg>
)
const SpinnerIcon = () => (
  <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
  </svg>
)
const ArrowRightIcon = () => (
  <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M14 5l7 7m0 0l-7 7m7-7H3"/>
  </svg>
)
const CheckCircleIcon = () => (
  <svg className="w-12 h-12 text-emerald-500" fill="none" stroke="currentColor" strokeWidth={1.5} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M9 12.75L11.25 15 15 9.75M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
  </svg>
)
const ExternalLinkIcon = () => (
  <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={1.8} viewBox="0 0 24 24">
    <path strokeLinecap="round" strokeLinejoin="round" d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
  </svg>
)

/* ─────────────────────────────────────────────────────────────────────────────
   Company header block — logo, name, tagline, description, contact row
───────────────────────────────────────────────────────────────────────────── */
function CompanyHeader() {
  return (
    <div className="flex flex-col items-center text-center px-8 pt-10 pb-8 bg-white">

      {/* Logo */}
      <a
        href={BRAND.website || '#'}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`${BRAND.name} website`}
        className="inline-block mb-5 rounded-lg p-1
                   ring-2 ring-transparent hover:ring-slate-100 transition-all duration-200"
      >
        <img
          src={BRAND.logoSrc}
          alt={BRAND.logoAlt}
          style={{ maxHeight: BRAND.logoMaxH, width: 'auto', maxWidth: 200 }}
          className="object-contain block select-none"
          draggable="false"
          onError={e => { e.currentTarget.style.display = 'none' }}
        />
      </a>

      {/* Company name */}
      <h2 className="text-[15px] font-bold text-slate-900 leading-tight tracking-tight">
        {BRAND.name}
      </h2>

      {/* Tagline */}
      {BRAND.tagline && (
        <p className="mt-1.5 text-[13px] text-slate-500 leading-snug">
          {BRAND.tagline}
        </p>
      )}

      {/* Description */}
      {BRAND.description && (
        <p className="mt-3 text-[13px] text-slate-500 leading-relaxed max-w-sm">
          {BRAND.description}
        </p>
      )}

      {/* Contact row */}
      <div className="mt-5 flex flex-wrap items-center justify-center gap-x-4 gap-y-2">
        {BRAND.website && (
          <a href={BRAND.website} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500
                       hover:text-slate-800 transition-colors">
            <GlobeIcon />
            {BRAND.website.replace(/^https?:\/\//, '')}
          </a>
        )}
        {BRAND.contactEmail && (
          <a href={`mailto:${BRAND.contactEmail}`}
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500
                       hover:text-slate-800 transition-colors">
            <MailIcon />
            {BRAND.contactEmail}
          </a>
        )}
        {BRAND.location && (
          <span className="inline-flex items-center gap-1.5 text-[12px] text-slate-400 select-none">
            <PinIcon />
            {BRAND.location}
          </span>
        )}
        {BRAND.linkedin && (
          <a href={BRAND.linkedin} target="_blank" rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500
                       hover:text-[#0A66C2] transition-colors">
            <LinkedInIcon />
            LinkedIn
          </a>
        )}
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   Form field — all question types
───────────────────────────────────────────────────────────────────────────── */
function FormField({ question, value, onChange, error }) {
  const { label, type, required, options, placeholder } = question
  const fieldId = `field-${question.question_id}`

  const baseClass = [
    'w-full rounded-md border px-4 py-3 text-[14px] text-slate-800',
    'placeholder-slate-400 bg-white outline-none transition-all duration-150',
    'focus:ring-2 focus:ring-offset-0',
    error
      ? 'border-rose-300 focus:ring-rose-100 bg-rose-50/40'
      : 'border-slate-300 hover:border-slate-400 focus:border-slate-500 focus:ring-slate-100',
  ].join(' ')

  return (
    <div className="flex flex-col gap-1.5">

      {/* Label */}
      <label htmlFor={fieldId}
        className="text-[13px] font-medium text-slate-700 leading-none">
        {label}
        {required && (
          <span className="text-rose-500 ml-1" aria-label="required">*</span>
        )}
      </label>

      {/* Controls */}
      {type === 'short_text' && (
        <input id={fieldId} type="text" value={value || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''}
          className={baseClass} autoComplete="off" />
      )}

      {type === 'email' && (
        <input id={fieldId} type="email" value={value || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || 'you@company.com'}
          className={baseClass} autoComplete="email" />
      )}

      {type === 'phone' && (
        <input id={fieldId} type="tel" value={value || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || '+91 98765 43210'}
          className={baseClass} autoComplete="tel" />
      )}

      {type === 'number' && (
        <input id={fieldId} type="number" value={value || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''}
          className={baseClass} />
      )}

      {type === 'long_text' && (
        <textarea id={fieldId} value={value || ''}
          onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''}
          rows={4}
          className={`${baseClass} resize-none leading-relaxed`} />
      )}

      {type === 'dropdown' && (
        <div className="relative">
          <select id={fieldId} value={value || ''}
            onChange={e => onChange(e.target.value)}
            className={`${baseClass} pr-10 appearance-none cursor-pointer`}>
            <option value="">Select an option</option>
            {(options || []).map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>
          <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
            <ChevronDownIcon />
          </div>
        </div>
      )}

      {type === 'radio' && (
        <div className="flex flex-col gap-2.5 mt-0.5">
          {(options || []).map(o => (
            <label key={o.value} className="flex items-center gap-3 cursor-pointer group select-none">
              <input type="radio" name={fieldId} value={o.value}
                checked={value === o.value} onChange={() => onChange(o.value)}
                className="w-4 h-4 border-slate-300 text-slate-900 focus:ring-slate-300 cursor-pointer" />
              <span className="text-[14px] text-slate-700 group-hover:text-slate-900 transition-colors">
                {o.label}
              </span>
            </label>
          ))}
        </div>
      )}

      {type === 'checkbox' && (
        <div className="flex flex-col gap-2.5 mt-0.5">
          {(options || []).map(o => {
            const checked = Array.isArray(value) ? value.includes(o.value) : false
            const toggle = () => {
              const cur = Array.isArray(value) ? value : []
              onChange(checked ? cur.filter(v => v !== o.value) : [...cur, o.value])
            }
            return (
              <label key={o.value} className="flex items-center gap-3 cursor-pointer group select-none">
                <input type="checkbox" checked={checked} onChange={toggle}
                  className="w-4 h-4 rounded border-slate-300 text-slate-900 focus:ring-slate-300 cursor-pointer" />
                <span className="text-[14px] text-slate-700 group-hover:text-slate-900 transition-colors">
                  {o.label}
                </span>
              </label>
            )
          })}
        </div>
      )}

      {/* Inline validation error */}
      {error && (
        <p role="alert" className="flex items-center gap-1.5 text-[12px] text-rose-600 mt-0.5">
          <AlertIcon />
          {error}
        </p>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────────────
   PAGE ROOT
───────────────────────────────────────────────────────────────────────────── */
export default function PublicForm() {
  const { form_id }    = useParams()
  const [searchParams] = useSearchParams()

  const source      = searchParams.get('source')      || 'other'
  const campaign_id = searchParams.get('campaign_id') || searchParams.get('campaign') || null

  const [form,       setForm]       = useState(null)
  const [loading,    setLoading]    = useState(true)
  const [notFound,   setNotFound]   = useState(false)
  const [answers,    setAnswers]    = useState({})
  const [errors,     setErrors]     = useState({})
  const [submitting, setSubmitting] = useState(false)
  const [submitted,  setSubmitted]  = useState(false)
  const [submitErr,  setSubmitErr]  = useState(null)

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
    const errs = {}
    for (const q of (form?.questions || [])) {
      const val = answers[q.question_id]
      if (q.required) {
        const empty = val === undefined || val === null || val === '' ||
          (Array.isArray(val) && val.length === 0)
        if (empty) errs[q.question_id] = `${q.label} is required`
      }
      if (q.type === 'email' && val) {
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(val).trim()))
          errs[q.question_id] = 'Please enter a valid email address'
      }
    }
    setErrors(errs)
    return Object.keys(errs).length === 0
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
      await submitPublicForm(form_id, { answers: answerList, source, campaign_id })
      setSubmitted(true)
    } catch (err) {
      setSubmitErr(err.message || 'Something went wrong. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  /* ── shared page shell ────────────────────────────────────────────────── */
  const shell = 'min-h-screen bg-[#f3f4f6] flex flex-col items-center justify-start py-10 px-4'

  /* ── Loading ──────────────────────────────────────────────────────────── */
  if (loading) return (
    <div className={`${shell} justify-center`}>
      <div className="flex flex-col items-center gap-5">
        <img
          src={BRAND.logoSrc}
          alt={BRAND.logoAlt}
          style={{ maxHeight: BRAND.logoMaxH, width: 'auto', opacity: 0.4 }}
          className="object-contain"
          onError={e => { e.currentTarget.style.display = 'none' }}
        />
        <SpinnerIcon />
        <p className="text-[13px] text-slate-400">Loading form…</p>
      </div>
    </div>
  )

  /* ── Not found ────────────────────────────────────────────────────────── */
  if (notFound || !form) return (
    <div className={`${shell} justify-center`}>
      <div className="w-full max-w-[480px] bg-white rounded-2xl shadow-sm
                      border border-slate-200 overflow-hidden">
        <div className="h-1 w-full bg-slate-900" />
        <div className="p-10 flex flex-col items-center text-center">
          <img
            src={BRAND.logoSrc}
            alt={BRAND.logoAlt}
            style={{ maxHeight: 44, width: 'auto', opacity: 0.5 }}
            className="object-contain mx-auto mb-7"
            onError={e => { e.currentTarget.style.display = 'none' }}
          />
          <div className="w-12 h-12 rounded-full bg-slate-100 flex items-center justify-center mb-4">
            <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
            </svg>
          </div>
          <h1 className="text-[17px] font-bold text-slate-800 mb-2">Form Not Found</h1>
          <p className="text-[13px] text-slate-500 leading-relaxed">
            This form may have been removed or is no longer accepting responses.
          </p>
          {BRAND.contactEmail && (
            <p className="text-[12px] text-slate-400 mt-5">
              Need help?{' '}
              <a href={`mailto:${BRAND.contactEmail}`}
                className="underline underline-offset-2 hover:text-slate-700 transition-colors">
                {BRAND.contactEmail}
              </a>
            </p>
          )}
        </div>
      </div>
    </div>
  )

  /* ── Success ──────────────────────────────────────────────────────────── */
  if (submitted) return (
    <div className={`${shell} justify-center`}>
      <div className="w-full max-w-[480px] bg-white rounded-2xl shadow-sm
                      border border-slate-200 overflow-hidden">
        <div className="h-1 w-full bg-slate-900" />
        <div className="p-10 flex flex-col items-center text-center">
          <img
            src={BRAND.logoSrc}
            alt={BRAND.logoAlt}
            style={{ maxHeight: BRAND.logoMaxH, width: 'auto' }}
            className="object-contain mx-auto mb-8"
            onError={e => { e.currentTarget.style.display = 'none' }}
          />
          <CheckCircleIcon />
          <h1 className="mt-5 text-[20px] font-bold text-slate-900">Response Received</h1>
          <p className="mt-3 text-[14px] text-slate-500 leading-relaxed max-w-xs">
            Thank you for reaching out to{' '}
            <span className="font-semibold text-slate-800">{BRAND.name}</span>.
            Our team will review your submission and be in touch shortly.
          </p>
          {BRAND.website && (
            <a href={BRAND.website} target="_blank" rel="noopener noreferrer"
              className="mt-7 inline-flex items-center gap-1.5 text-[12px] text-slate-400
                         hover:text-slate-700 transition-colors">
              <ExternalLinkIcon />
              Visit {BRAND.website.replace(/^https?:\/\//, '')}
            </a>
          )}
        </div>
      </div>
    </div>
  )

  /* ── Main form ────────────────────────────────────────────────────────── */
  const plt = PLATFORM_LABELS[source] ?? PLATFORM_LABELS.other
  const sortedQuestions = [...(form.questions || [])].sort(
    (a, b) => a.display_order - b.display_order
  )
  const hasRequired = sortedQuestions.some(q => q.required)

  return (
    <div className={shell}>
      <div className="w-full max-w-[600px]">

        {/* ── Card ───────────────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden">

          {/* Top accent line */}
          <div className="h-[3px] w-full bg-slate-900" />

          {/* ── Company header ─────────────────────────────────────────── */}
          <CompanyHeader />

          {/* Divider */}
          <div className="h-px bg-slate-200" />

          {/* ── Form header ────────────────────────────────────────────── */}
          <div className="px-8 pt-8 pb-6">

            {/* Platform badge — only when a real campaign source is passed */}
            {source && source !== 'other' && (
              <span className={`inline-flex items-center px-2.5 py-1 rounded-full
                               text-[11px] font-semibold border mb-5 ${plt.color}`}>
                {plt.label}
              </span>
            )}

            {/* Form title */}
            <h1 className="text-[24px] font-bold text-slate-900 leading-tight">
              {form.name}
            </h1>

            {/* Category pill */}
            {form.category && (
              <p className="mt-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-widest">
                {form.category}
              </p>
            )}

            {/* Form description */}
            <p className="mt-3 text-[14px] text-slate-500 leading-relaxed">
              {form.description
                ? form.description
                : 'Please complete the form below and our team will be in touch with you regarding your enquiry.'}
            </p>

            {/* Required fields note */}
            {hasRequired && (
              <p className="mt-3 text-[12.5px] text-slate-400">
                Fields marked{' '}
                <span className="text-rose-500 font-semibold">*</span>
                {' '}are required.
              </p>
            )}
          </div>

          {/* Divider */}
          <div className="h-px bg-slate-100" />

          {/* ── Form body ──────────────────────────────────────────────── */}
          <form onSubmit={handleSubmit} className="px-8 py-8" noValidate>

            {/* Submit error banner */}
            {submitErr && (
              <div role="alert"
                className="mb-6 flex items-start gap-3 p-4 rounded-lg
                           bg-rose-50 border border-rose-200 text-[13px] text-rose-700">
                <AlertIcon />
                <span className="leading-snug">{submitErr}</span>
              </div>
            )}

            {/* Fields */}
            <div className="space-y-7">
              {sortedQuestions.map(q => (
                <FormField
                  key={q.question_id}
                  question={q}
                  value={answers[q.question_id]}
                  onChange={val => setAnswer(q.question_id, val)}
                  error={errors[q.question_id]}
                />
              ))}
            </div>

            {/* Honeypot anti-bot */}
            <input
              type="text" name="hp" autoComplete="off" tabIndex={-1} aria-hidden="true"
              className="absolute left-[-9999px] opacity-0 pointer-events-none"
            />

            {/* Submit */}
            <button
              type="submit"
              disabled={submitting}
              className={[
                'mt-9 w-full py-3.5 px-6 rounded-lg',
                'text-[14px] font-semibold text-white',
                'flex items-center justify-center gap-2.5',
                'bg-slate-900 hover:bg-slate-800 active:bg-slate-950',
                'transition-all duration-150 shadow-sm hover:shadow-md',
                'focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-slate-700',
                'disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none',
              ].join(' ')}
            >
              {submitting
                ? <><SpinnerIcon /> Submitting…</>
                : <><span>Submit Enquiry</span><ArrowRightIcon /></>
              }
            </button>

            {/* Privacy note */}
            <div className="mt-7 pt-6 border-t border-slate-100">
              <p className="text-[12px] text-slate-400 text-center leading-relaxed">
                Your information will only be used for the purpose described in this form
                and will not be shared with third parties.
                {BRAND.privacyPolicyUrl && (
                  <>
                    {' '}
                    <a href={BRAND.privacyPolicyUrl} target="_blank" rel="noopener noreferrer"
                      className="underline underline-offset-2 hover:text-slate-600 transition-colors">
                      Privacy Policy
                    </a>
                  </>
                )}
              </p>
            </div>
          </form>
        </div>

        {/* ── Page footer ────────────────────────────────────────────────── */}
        <div className="mt-6 flex flex-wrap items-center justify-center gap-x-3 gap-y-1
                        text-[11px] text-slate-400">
          <span>
            ©{' '}{new Date().getFullYear()}{' '}
            <a href={BRAND.website || '#'} target="_blank" rel="noopener noreferrer"
              className="hover:text-slate-600 transition-colors">
              {BRAND.name}
            </a>
          </span>
          {BRAND.linkedin && (
            <>
              <span aria-hidden="true">·</span>
              <a href={BRAND.linkedin} target="_blank" rel="noopener noreferrer"
                className="hover:text-slate-600 transition-colors">LinkedIn</a>
            </>
          )}
          {BRAND.contactEmail && (
            <>
              <span aria-hidden="true">·</span>
              <a href={`mailto:${BRAND.contactEmail}`}
                className="hover:text-slate-600 transition-colors">{BRAND.contactEmail}</a>
            </>
          )}
        </div>

      </div>
    </div>
  )
}
