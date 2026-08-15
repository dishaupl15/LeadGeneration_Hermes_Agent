/**
 * PublicForm.jsx
 * ──────────────
 * Public-facing branded form page served at  /f/:form_id
 *
 * ● No CRM login required — anyone with the link can fill this form.
 * ● All submission / API / MongoDB logic is UNCHANGED.
 * ● Company branding is centralised in  src/config/brandConfig.js
 *   Edit that file to update the logo, company name, tagline, colours, or privacy URL.
 *   Every generated form inherits those values automatically.
 */

import { useState, useEffect } from 'react'
import { useParams, useSearchParams } from 'react-router-dom'
import { getPublicForm, submitPublicForm } from '../services/api'
import { BRAND } from '../config/brandConfig'

/* ── platform source badge metadata ──────────────────────────────────────── */
const PLATFORM_LABELS = {
  linkedin: { label: 'LinkedIn',  color: 'bg-sky-50 text-sky-700 border-sky-200' },
  x:        { label: 'X / Twitter', color: 'bg-slate-50 text-slate-600 border-slate-200' },
  whatsapp: { label: 'WhatsApp',  color: 'bg-green-50 text-green-700 border-green-200' },
  facebook: { label: 'Facebook',  color: 'bg-blue-50 text-blue-700 border-blue-200' },
  website:  { label: 'Website',   color: 'bg-violet-50 text-violet-700 border-violet-200' },
  other:    { label: 'Other',     color: 'bg-slate-50 text-slate-500 border-slate-200' },
}

/* ══════════════════════════════════════════════════════════════════════════════
   COMPANY HEADER
   Shown at the top of the card — logo, name, tagline, description, contact row.
   ══════════════════════════════════════════════════════════════════════════════ */
function CompanyHeader() {
  return (
    <div className="flex flex-col items-center text-center px-8 pt-10 pb-8">

      {/* ── Logo ── */}
      <a
        href={BRAND.website}
        target="_blank"
        rel="noopener noreferrer"
        aria-label={`${BRAND.name} website`}
        className="inline-flex items-center justify-center mb-5 rounded-xl
                   ring-2 ring-transparent hover:ring-slate-200 transition-all duration-200 p-1"
      >
        <img
          src={BRAND.logoSrc}
          alt={BRAND.logoAlt}
          style={{ maxHeight: BRAND.logoMaxH, width: 'auto', maxWidth: 220 }}
          className="object-contain select-none"
          draggable="false"
        />
      </a>

      {/* ── Company name ── */}
      <h2 className="text-[15px] font-bold text-slate-900 tracking-tight leading-tight">
        {BRAND.name}
      </h2>

      {/* ── Tagline ── */}
      {BRAND.tagline && (
        <p className="mt-1.5 text-[13px] font-medium text-slate-500 leading-snug max-w-xs">
          {BRAND.tagline}
        </p>
      )}

      {/* ── Description ── */}
      {BRAND.description && (
        <p className="mt-3 text-[13px] text-slate-500 leading-relaxed max-w-sm">
          {BRAND.description}
        </p>
      )}

      {/* ── Contact row ── */}
      <div className="mt-5 flex flex-wrap items-center justify-center gap-x-5 gap-y-2">

        {BRAND.website && (
          <a
            href={BRAND.website}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500
                       hover:text-slate-800 transition-colors duration-150"
          >
            <GlobeIcon />
            {BRAND.website.replace(/^https?:\/\//, '')}
          </a>
        )}

        {BRAND.contactEmail && (
          <a
            href={`mailto:${BRAND.contactEmail}`}
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500
                       hover:text-slate-800 transition-colors duration-150"
          >
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
          <a
            href={BRAND.linkedin}
            target="_blank"
            rel="noopener noreferrer"
            aria-label="LinkedIn"
            className="inline-flex items-center gap-1.5 text-[12px] text-slate-500
                       hover:text-[#0A66C2] transition-colors duration-150"
          >
            <LinkedInIcon />
            LinkedIn
          </a>
        )}
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   FORM FIELD — all question types, upgraded visual style
   ══════════════════════════════════════════════════════════════════════════════ */
function FormField({ question, value, onChange, error }) {
  const { label, type, required, options, placeholder } = question
  const id = `field-${question.question_id}`

  const baseInput = [
    'w-full rounded-lg border px-4 py-3 text-[14px] text-slate-800 leading-normal',
    'placeholder-slate-400 bg-white outline-none transition-all duration-150',
    'focus:ring-2 focus:ring-offset-0 shadow-sm',
    error
      ? 'border-rose-300 focus:ring-rose-200 bg-rose-50/30'
      : `border-slate-200 ${BRAND.accentRing} ${BRAND.accentBorder} hover:border-slate-300`,
  ].join(' ')

  return (
    <div className="flex flex-col gap-2">

      {/* Label */}
      <label htmlFor={id} className="text-[13px] font-semibold text-slate-700 leading-none select-none">
        {label}
        {required && (
          <span className="text-rose-500 ml-1" aria-label="required field">*</span>
        )}
      </label>

      {/* Input controls */}
      {type === 'short_text' && (
        <input id={id} type="text" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''} className={baseInput} autoComplete="off" />
      )}

      {type === 'email' && (
        <input id={id} type="email" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || 'you@company.com'} className={baseInput} autoComplete="email" />
      )}

      {type === 'phone' && (
        <input id={id} type="tel" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || '+91 98765 43210'} className={baseInput} autoComplete="tel" />
      )}

      {type === 'number' && (
        <input id={id} type="number" value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''} className={baseInput} />
      )}

      {type === 'long_text' && (
        <textarea id={id} value={value || ''} onChange={e => onChange(e.target.value)}
          placeholder={placeholder || ''} rows={4}
          className={`${baseInput} resize-none leading-relaxed`} />
      )}

      {type === 'dropdown' && (
        <div className="relative">
          <select id={id} value={value || ''} onChange={e => onChange(e.target.value)}
            className={`${baseInput} pr-10 appearance-none cursor-pointer`}>
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
        <div className="flex flex-col gap-3 mt-0.5">
          {(options || []).map(o => (
            <label key={o.value}
              className="flex items-center gap-3 cursor-pointer group select-none">
              <input
                type="radio" name={id} value={o.value}
                checked={value === o.value}
                onChange={() => onChange(o.value)}
                className="w-4 h-4 border-slate-300 text-slate-900 focus:ring-slate-400 cursor-pointer"
              />
              <span className="text-[14px] text-slate-700 group-hover:text-slate-900 transition-colors">
                {o.label}
              </span>
            </label>
          ))}
        </div>
      )}

      {type === 'checkbox' && (
        <div className="flex flex-col gap-3 mt-0.5">
          {(options || []).map(o => {
            const checked = Array.isArray(value) ? value.includes(o.value) : false
            const toggle = () => {
              const cur = Array.isArray(value) ? value : []
              onChange(checked ? cur.filter(v => v !== o.value) : [...cur, o.value])
            }
            return (
              <label key={o.value}
                className="flex items-center gap-3 cursor-pointer group select-none">
                <input
                  type="checkbox" checked={checked} onChange={toggle}
                  className="w-4 h-4 rounded border-slate-300 text-slate-900 focus:ring-slate-400 cursor-pointer"
                />
                <span className="text-[14px] text-slate-700 group-hover:text-slate-900 transition-colors">
                  {o.label}
                </span>
              </label>
            )
          })}
        </div>
      )}

      {/* Inline error */}
      {error && (
        <p role="alert" className="flex items-center gap-1.5 text-[12px] text-rose-600 mt-0.5">
          <ErrorCircleIcon />
          {error}
        </p>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   FORM FOOTER — privacy / data-use note
   ══════════════════════════════════════════════════════════════════════════════ */
function FormFooter() {
  return (
    <div className="mt-8 pt-5 border-t border-slate-100">
      <p className="text-[12px] text-slate-400 text-center leading-relaxed">
        Your information will be used only for the purpose described in this form
        and will not be shared with third parties.
        {BRAND.privacyPolicyUrl && (
          <>
            {' '}
            <a
              href={BRAND.privacyPolicyUrl}
              target="_blank"
              rel="noopener noreferrer"
              className="underline underline-offset-2 hover:text-slate-600 transition-colors"
            >
              Privacy Policy
            </a>
          </>
        )}
      </p>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   ICON HELPERS — kept inline to avoid extra dependencies
   ══════════════════════════════════════════════════════════════════════════════ */
const sz = 'w-3.5 h-3.5 flex-shrink-0'

function GlobeIcon() {
  return (
    <svg className={sz} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M21 12a9 9 0 01-9 9m9-9a9 9 0 00-9-9m9 9H3m9 9a9 9 0 01-9-9m9 9c1.657 0 3-4.03 3-9s-1.343-9-3-9m0 18c-1.657 0-3-4.03-3-9s1.343-9 3-9"/>
    </svg>
  )
}

function MailIcon() {
  return (
    <svg className={sz} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z"/>
    </svg>
  )
}

function PinIcon() {
  return (
    <svg className={sz} fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M17.657 16.657L13.414 20.9a2 2 0 01-2.828 0l-4.243-4.243a8 8 0 1111.314 0z"/>
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z"/>
    </svg>
  )
}

function LinkedInIcon() {
  return (
    <svg className={sz} fill="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path d="M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.222 0h.003z"/>
    </svg>
  )
}

function ChevronDownIcon() {
  return (
    <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
    </svg>
  )
}

function ErrorCircleIcon() {
  return (
    <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
        d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
    </svg>
  )
}

function SpinnerIcon() {
  return (
    <svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
    </svg>
  )
}

function ArrowRightIcon() {
  return (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3"/>
    </svg>
  )
}

function ExternalLinkIcon() {
  return (
    <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8}
        d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
    </svg>
  )
}

function CheckIcon() {
  return (
    <svg className="w-6 h-6 text-emerald-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7"/>
    </svg>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   PAGE ROOT
   ══════════════════════════════════════════════════════════════════════════════ */
export default function PublicForm() {
  const { form_id }    = useParams()
  const [searchParams] = useSearchParams()

  // Tracking params injected by the platform campaign link
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

  // ── Fetch form definition (unchanged) ─────────────────────────────────────
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

  // ── Client-side validation (unchanged) ────────────────────────────────────
  const validate = () => {
    const newErrors = {}
    for (const q of (form?.questions || [])) {
      const val = answers[q.question_id]
      if (q.required) {
        const isEmpty = val === undefined || val === null || val === '' ||
          (Array.isArray(val) && val.length === 0)
        if (isEmpty) newErrors[q.question_id] = `${q.label} is required`
      }
      if (q.type === 'email' && val) {
        if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(val).trim()))
          newErrors[q.question_id] = 'Please enter a valid email address'
      }
    }
    setErrors(newErrors)
    return Object.keys(newErrors).length === 0
  }

  // ── Submission (unchanged logic) ──────────────────────────────────────────
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

  // ── Shared page shell ──────────────────────────────────────────────────────
  const pageBg = 'min-h-screen bg-slate-50 py-8 px-4 sm:px-6'

  /* ── Loading state ─────────────────────────────────────────────────────── */
  if (loading) return (
    <div className={`${pageBg} flex items-center justify-center`}>
      <div className="flex flex-col items-center gap-4">
        <img
          src={BRAND.logoSrc}
          alt={BRAND.logoAlt}
          style={{ maxHeight: BRAND.logoMaxH, width: 'auto', opacity: 0.45 }}
          className="object-contain"
        />
        <SpinnerIcon />
      </div>
    </div>
  )

  /* ── Not found ─────────────────────────────────────────────────────────── */
  if (notFound || !form) return (
    <div className={`${pageBg} flex items-center justify-center`}>
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 p-10
                      max-w-sm w-full text-center">
        <img
          src={BRAND.logoSrc}
          alt={BRAND.logoAlt}
          style={{ maxHeight: 42, width: 'auto' }}
          className="object-contain mx-auto mb-7 opacity-55"
        />
        <div className="w-11 h-11 rounded-full bg-slate-100 flex items-center
                        justify-center mx-auto mb-4">
          <svg className="w-5 h-5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M9.172 16.172a4 4 0 015.656 0M9 10h.01M15 10h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
        </div>
        <h1 className="text-base font-bold text-slate-800 mb-2">Form Not Found</h1>
        <p className="text-sm text-slate-500 leading-relaxed">
          This form may have been removed or is no longer accepting responses.
        </p>
        {BRAND.contactEmail && (
          <p className="text-xs text-slate-400 mt-4">
            Need help?{' '}
            <a href={`mailto:${BRAND.contactEmail}`}
              className="underline underline-offset-2 hover:text-slate-600 transition-colors">
              {BRAND.contactEmail}
            </a>
          </p>
        )}
      </div>
    </div>
  )

  /* ── Success state ─────────────────────────────────────────────────────── */
  if (submitted) return (
    <div className={`${pageBg} flex items-center justify-center`}>
      <div className="bg-white rounded-2xl shadow-sm border border-slate-200 overflow-hidden
                      max-w-sm w-full text-center">

        {/* Thin accent bar at top */}
        <div className={`h-1 w-full ${BRAND.accentBarBg}`} />

        <div className="p-10">
          {/* Logo stays visible */}
          <img
            src={BRAND.logoSrc}
            alt={BRAND.logoAlt}
            style={{ maxHeight: 48, width: 'auto' }}
            className="object-contain mx-auto mb-7"
          />

          {/* Success icon */}
          <div className="w-12 h-12 rounded-full bg-emerald-50 flex items-center
                          justify-center mx-auto mb-5">
            <CheckIcon />
          </div>

          <h1 className="text-[18px] font-bold text-slate-900 mb-3">Response Received</h1>
          <p className="text-[14px] text-slate-600 leading-relaxed">
            Thank you for reaching out to{' '}
            <span className="font-semibold text-slate-800">{BRAND.name}</span>.
            Our team will review your information and contact you shortly.
          </p>

          {BRAND.website && (
            <a
              href={BRAND.website}
              target="_blank"
              rel="noopener noreferrer"
              className="mt-7 inline-flex items-center gap-1.5 text-[12px] text-slate-500
                         hover:text-slate-800 transition-colors"
            >
              <ExternalLinkIcon />
              Visit {BRAND.website.replace(/^https?:\/\//, '')}
            </a>
          )}
        </div>
      </div>
    </div>
  )

  /* ── Main form page ────────────────────────────────────────────────────── */
  const plt = PLATFORM_LABELS[source] ?? PLATFORM_LABELS.other
  const sortedQuestions = [...(form.questions || [])].sort(
    (a, b) => a.display_order - b.display_order
  )
  const hasRequiredFields = sortedQuestions.some(q => q.required)

  return (
    <div className={pageBg}>
      <div className="max-w-[580px] mx-auto">

        {/* ── Main card ──────────────────────────────────────────────────── */}
        <div className="bg-white rounded-2xl shadow-md border border-slate-200 overflow-hidden">

          {/* Thin branded accent bar — the single brand colour touch */}
          <div className={`h-1 w-full ${BRAND.accentBarBg}`} />

          {/* Company header */}
          <CompanyHeader />

          {/* Divider */}
          <div className="h-px bg-slate-100" />

          {/* Form header — title, category, description */}
          <div className="px-8 pt-7 pb-6">

            {/* Source / platform badge — only shown when a campaign tracking link was used */}
            {source && source !== 'other' && (
              <span className={`inline-flex items-center px-2.5 py-1 rounded-full
                               text-[11px] font-semibold border mb-4 ${plt.color}`}>
                {plt.label}
              </span>
            )}

            {/* Form title */}
            <h1 className="text-[22px] font-bold text-slate-900 leading-tight">
              {form.name}
            </h1>

            {/* Category label */}
            {form.category && (
              <p className="mt-1 text-[11px] font-semibold text-slate-400 uppercase tracking-widest">
                {form.category}
              </p>
            )}

            {/* Form description — from CRM config, or a generic professional fallback */}
            <p className="mt-3 text-[14px] text-slate-500 leading-relaxed">
              {form.description
                ? form.description
                : 'Please complete the form below and our team will be in touch with you regarding your enquiry.'}
            </p>

            {hasRequiredFields && (
              <p className="mt-3 text-[12px] text-slate-400">
                Fields marked <span className="text-rose-500 font-semibold">*</span> are required.
              </p>
            )}
          </div>

          {/* Divider */}
          <div className="h-px bg-slate-100" />

          {/* ── Form body ─────────────────────────────────────────────────── */}
          <form onSubmit={handleSubmit} className="px-8 py-7" noValidate>

            {/* Submission error banner */}
            {submitErr && (
              <div role="alert"
                className="mb-6 flex items-start gap-3 p-4 rounded-lg
                           bg-rose-50 border border-rose-200 text-[13px] text-rose-700">
                <ErrorCircleIcon />
                <span>{submitErr}</span>
              </div>
            )}

            {/* Dynamic form fields */}
            <div className="space-y-6">
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

            {/* Honeypot — invisible to real users, traps bots */}
            <input
              type="text"
              name="hp"
              autoComplete="off"
              className="absolute left-[-9999px] opacity-0 pointer-events-none"
              tabIndex={-1}
              aria-hidden="true"
            />

            {/* Submit button */}
            <button
              type="submit"
              disabled={submitting}
              className={[
                'mt-8 w-full py-3.5 rounded-lg text-[14px] font-semibold text-white',
                'flex items-center justify-center gap-2.5',
                'transition-all duration-150 shadow-sm hover:shadow-md',
                'focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-slate-700',
                'disabled:opacity-50 disabled:cursor-not-allowed disabled:shadow-none',
                BRAND.accentBg,
                BRAND.accentHoverBg,
              ].join(' ')}
            >
              {submitting ? (
                <>
                  <SpinnerIcon />
                  Submitting…
                </>
              ) : (
                <>
                  Submit Enquiry
                  <ArrowRightIcon />
                </>
              )}
            </button>

            {/* Privacy / data-use footer */}
            <FormFooter />
          </form>
        </div>

        {/* ── Page footer ────────────────────────────────────────────────── */}
        <div className="mt-5 flex flex-wrap items-center justify-center gap-x-3 gap-y-1
                        text-[11px] text-slate-400">
          <span>
            © {new Date().getFullYear()}{' '}
            <a
              href={BRAND.website}
              target="_blank"
              rel="noopener noreferrer"
              className="hover:text-slate-600 transition-colors"
            >
              {BRAND.name}
            </a>
          </span>
          {BRAND.linkedin && (
            <>
              <span aria-hidden="true">·</span>
              <a
                href={BRAND.linkedin}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-slate-600 transition-colors"
              >
                LinkedIn
              </a>
            </>
          )}
          {BRAND.contactEmail && (
            <>
              <span aria-hidden="true">·</span>
              <a
                href={`mailto:${BRAND.contactEmail}`}
                className="hover:text-slate-600 transition-colors"
              >
                {BRAND.contactEmail}
              </a>
            </>
          )}
        </div>

      </div>
    </div>
  )
}
