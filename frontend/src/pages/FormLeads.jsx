/**
 * FormLeads.jsx
 * ─────────────
 * Main CRM admin page for the Social Lead Collection / Form Builder feature.
 *
 * Views:
 *   "list"    — shows all forms
 *   "builder" — create / edit a form
 *   "detail"  — form detail with tracking links + submissions
 */

import { useState, useEffect, useCallback } from 'react'
import { CATEGORIES } from '../config/categories'
import {
  createForm, listForms, getFormDetail,
  updateForm, deleteForm, createCampaign, listSubmissions,
} from '../services/api'

const BASE_URL = 'http://localhost:8002'
const FRONTEND_BASE = window.location.origin

const QUESTION_TYPES = [
  { value: 'short_text', label: 'Short Text' },
  { value: 'email',      label: 'Email' },
  { value: 'phone',      label: 'Phone' },
  { value: 'number',     label: 'Number' },
  { value: 'long_text',  label: 'Long Text' },
  { value: 'dropdown',   label: 'Dropdown' },
  { value: 'radio',      label: 'Radio' },
  { value: 'checkbox',   label: 'Checkbox' },
]

const PLATFORMS = [
  { id: 'linkedin',  label: 'LinkedIn',   icon: '💼', color: 'bg-sky-50 border-sky-200 text-sky-700' },
  { id: 'x',         label: 'X / Twitter', icon: '𝕏',  color: 'bg-slate-50 border-slate-200 text-slate-700' },
  { id: 'whatsapp',  label: 'WhatsApp',   icon: '💬', color: 'bg-green-50 border-green-200 text-green-700' },
  { id: 'facebook',  label: 'Facebook',   icon: '👥', color: 'bg-blue-50 border-blue-200 text-blue-700' },
  { id: 'website',   label: 'Website',    icon: '🌐', color: 'bg-indigo-50 border-indigo-200 text-indigo-700' },
  { id: 'other',     label: 'Other',      icon: '🔗', color: 'bg-slate-50 border-slate-200 text-slate-500' },
]

/* ── tiny helpers ──────────────────────────────────────────────────────────── */
function uid() { return 'q_' + Math.random().toString(36).slice(2, 10) }

function fmtDate(iso) {
  if (!iso) return '—'
  try { return new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', hour12: true }).format(new Date(iso)) }
  catch { return iso?.slice(0, 16) }
}

function CopyBtn({ text }) {
  const [copied, setCopied] = useState(false)
  const handle = () => {
    navigator.clipboard.writeText(text).then(() => { setCopied(true); setTimeout(() => setCopied(false), 2000) })
  }
  return (
    <button onClick={handle}
      className="flex-shrink-0 px-3 py-1.5 rounded-lg text-xs font-semibold border
                 border-slate-200 bg-white text-slate-600 hover:bg-indigo-50 hover:border-indigo-300
                 hover:text-indigo-700 transition-colors">
      {copied ? '✓ Copied' : 'Copy'}
    </button>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   FORM BUILDER
   ══════════════════════════════════════════════════════════════════════════════ */
function FormBuilder({ initialData, onSave, onCancel }) {
  const isEdit = Boolean(initialData)

  const [name,        setName]        = useState(initialData?.name        ?? '')
  const [category,    setCategory]    = useState(initialData?.category    ?? '')
  const [description, setDescription] = useState(initialData?.description ?? '')
  const [questions,   setQuestions]   = useState(
    initialData?.questions?.length
      ? initialData.questions
      : [{ question_id: uid(), label: '', type: 'short_text', required: false, options: [], display_order: 0, placeholder: '' }]
  )
  const [saving, setSaving] = useState(false)
  const [error,  setError]  = useState(null)

  const addQuestion = () => {
    setQuestions(prev => [
      ...prev,
      { question_id: uid(), label: '', type: 'short_text', required: false, options: [], display_order: prev.length, placeholder: '' },
    ])
  }

  const removeQuestion = (id) => setQuestions(prev => prev.filter(q => q.question_id !== id))

  const updateQuestion = (id, field, value) =>
    setQuestions(prev => prev.map(q => q.question_id === id ? { ...q, [field]: value } : q))

  const moveQuestion = (idx, dir) => {
    setQuestions(prev => {
      const arr = [...prev]
      const swap = idx + dir
      if (swap < 0 || swap >= arr.length) return arr;
      [arr[idx], arr[swap]] = [arr[swap], arr[idx]]
      return arr.map((q, i) => ({ ...q, display_order: i }))
    })
  }

  const addOption = (qid) =>
    setQuestions(prev => prev.map(q =>
      q.question_id === qid
        ? { ...q, options: [...q.options, { value: uid(), label: '' }] }
        : q
    ))

  const updateOption = (qid, oidx, val) =>
    setQuestions(prev => prev.map(q =>
      q.question_id === qid
        ? { ...q, options: q.options.map((o, i) => i === oidx ? { ...o, label: val, value: val.toLowerCase().replace(/\s+/g, '_') || o.value } : o) }
        : q
    ))

  const removeOption = (qid, oidx) =>
    setQuestions(prev => prev.map(q =>
      q.question_id === qid ? { ...q, options: q.options.filter((_, i) => i !== oidx) } : q
    ))

  const handleSubmit = async () => {
    setError(null)
    if (!name.trim())     return setError('Form name is required')
    if (!category.trim()) return setError('Category is required')
    const emptyQ = questions.find(q => !q.label.trim())
    if (emptyQ) return setError('All question labels must be filled in')
    const optQ = questions.find(q => ['dropdown','radio','checkbox'].includes(q.type) && q.options.length === 0)
    if (optQ) return setError(`"${optQ.label}" needs at least one option`)

    setSaving(true)
    try {
      const payload = {
        name: name.trim(),
        category: category.trim(),
        description: description.trim(),
        questions: questions.map((q, i) => ({ ...q, display_order: i })),
      }
      let result
      if (isEdit) {
        result = await updateForm(initialData.form_id, payload)
        onSave(result.form, null, false)
      } else {
        result = await createForm(payload)
        onSave(result.form, result.campaigns, true)
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setSaving(false)
    }
  }

  const needsOptions = (type) => ['dropdown', 'radio', 'checkbox'].includes(type)

  return (
    <div className="max-w-3xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4 mb-6">
        <button onClick={onCancel}
          className="w-9 h-9 flex items-center justify-center rounded-xl border border-slate-200
                     bg-white text-slate-500 hover:bg-slate-50 hover:text-slate-700 transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/>
          </svg>
        </button>
        <div>
          <h2 className="text-xl font-bold text-slate-900">{isEdit ? 'Edit Form' : 'Create Lead Form'}</h2>
          <p className="text-xs text-slate-400 mt-0.5">Build a form to collect leads from social platforms</p>
        </div>
      </div>

      {error && (
        <div className="mb-4 p-3 rounded-xl bg-rose-50 border border-rose-200 text-sm text-rose-700 flex items-center gap-2">
          <svg className="w-4 h-4 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
          </svg>
          {error}
        </div>
      )}

      {/* Form metadata */}
      <div className="crm-card p-5 mb-5">
        <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">Form Details</h3>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <div className="sm:col-span-2 flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-600">Form Name <span className="text-rose-400">*</span></label>
            <input type="text" value={name} onChange={e => setName(e.target.value)}
              placeholder="e.g. Real Estate Investor Survey"
              className="crm-input" maxLength={200} />
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-600">Category <span className="text-rose-400">*</span></label>
            <div className="relative">
              <select value={category} onChange={e => setCategory(e.target.value)} className="crm-input pr-9 appearance-none">
                <option value="">— Select category —</option>
                {CATEGORIES.map(c => <option key={c.label} value={c.label}>{c.icon} {c.label}</option>)}
              </select>
              <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                <svg className="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                </svg>
              </div>
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <label className="text-xs font-semibold text-slate-600">Description <span className="text-slate-400 font-normal">(optional)</span></label>
            <input type="text" value={description} onChange={e => setDescription(e.target.value)}
              placeholder="Brief description of this form…"
              className="crm-input" maxLength={500} />
          </div>
        </div>
      </div>

      {/* Questions */}
      <div className="crm-card p-5 mb-5">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">
            Questions <span className="text-slate-300 font-normal">({questions.length})</span>
          </h3>
        </div>

        <div className="space-y-3">
          {questions.map((q, idx) => (
            <div key={q.question_id}
              className="rounded-xl border border-slate-200 bg-slate-50/60 p-4">
              <div className="flex items-start gap-3">
                {/* drag handle / order */}
                <div className="flex flex-col gap-1 mt-1 flex-shrink-0">
                  <button onClick={() => moveQuestion(idx, -1)} disabled={idx === 0}
                    className="w-6 h-6 flex items-center justify-center rounded text-slate-400
                               hover:bg-slate-200 disabled:opacity-30 transition-colors">
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 15l7-7 7 7"/>
                    </svg>
                  </button>
                  <span className="text-[11px] text-slate-400 text-center font-mono">{idx + 1}</span>
                  <button onClick={() => moveQuestion(idx, 1)} disabled={idx === questions.length - 1}
                    className="w-6 h-6 flex items-center justify-center rounded text-slate-400
                               hover:bg-slate-200 disabled:opacity-30 transition-colors">
                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M19 9l-7 7-7-7"/>
                    </svg>
                  </button>
                </div>

                {/* question fields */}
                <div className="flex-1 grid grid-cols-1 sm:grid-cols-2 gap-3">
                  <div className="sm:col-span-2 flex flex-col gap-1">
                    <label className="text-[11px] font-semibold text-slate-500">Question Label</label>
                    <input type="text" value={q.label}
                      onChange={e => updateQuestion(q.question_id, 'label', e.target.value)}
                      placeholder="e.g. Full Name"
                      className="crm-input text-sm py-2" maxLength={300} />
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[11px] font-semibold text-slate-500">Type</label>
                    <div className="relative">
                      <select value={q.type}
                        onChange={e => updateQuestion(q.question_id, 'type', e.target.value)}
                        className="crm-input text-sm py-2 pr-8 appearance-none">
                        {QUESTION_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                      </select>
                      <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                        <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                        </svg>
                      </div>
                    </div>
                  </div>
                  <div className="flex flex-col gap-1">
                    <label className="text-[11px] font-semibold text-slate-500">Placeholder (optional)</label>
                    <input type="text" value={q.placeholder || ''}
                      onChange={e => updateQuestion(q.question_id, 'placeholder', e.target.value)}
                      placeholder="Hint text…"
                      className="crm-input text-sm py-2" maxLength={200} />
                  </div>
                  <div className="sm:col-span-2 flex items-center gap-2">
                    <input type="checkbox" id={`req-${q.question_id}`}
                      checked={q.required}
                      onChange={e => updateQuestion(q.question_id, 'required', e.target.checked)}
                      className="w-4 h-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" />
                    <label htmlFor={`req-${q.question_id}`} className="text-xs font-semibold text-slate-600 cursor-pointer">
                      Required field
                    </label>
                  </div>

                  {/* Options (for dropdown/radio/checkbox) */}
                  {needsOptions(q.type) && (
                    <div className="sm:col-span-2">
                      <label className="text-[11px] font-semibold text-slate-500 mb-1.5 block">Options</label>
                      <div className="space-y-1.5">
                        {q.options.map((opt, oi) => (
                          <div key={oi} className="flex items-center gap-2">
                            <input type="text" value={opt.label}
                              onChange={e => updateOption(q.question_id, oi, e.target.value)}
                              placeholder={`Option ${oi + 1}`}
                              className="crm-input text-sm py-1.5 flex-1" maxLength={200} />
                            <button onClick={() => removeOption(q.question_id, oi)}
                              className="w-7 h-7 flex items-center justify-center rounded text-slate-400
                                         hover:bg-rose-100 hover:text-rose-600 transition-colors">
                              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12"/>
                              </svg>
                            </button>
                          </div>
                        ))}
                        <button onClick={() => addOption(q.question_id)}
                          className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold flex items-center gap-1 mt-1">
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4"/>
                          </svg>
                          Add option
                        </button>
                      </div>
                    </div>
                  )}
                </div>

                {/* delete question */}
                <button onClick={() => removeQuestion(q.question_id)}
                  disabled={questions.length === 1}
                  className="w-8 h-8 flex items-center justify-center rounded-lg flex-shrink-0
                             text-slate-400 hover:bg-rose-100 hover:text-rose-600
                             disabled:opacity-30 disabled:cursor-not-allowed transition-colors mt-1">
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                      d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                  </svg>
                </button>
              </div>
            </div>
          ))}
        </div>

        <button onClick={addQuestion}
          className="mt-4 w-full py-2.5 rounded-xl border-2 border-dashed border-slate-300
                     text-sm font-semibold text-slate-500 hover:border-indigo-400
                     hover:text-indigo-600 hover:bg-indigo-50/50 transition-colors flex items-center justify-center gap-2">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4"/>
          </svg>
          Add Question
        </button>
      </div>

      {/* Save */}
      <div className="flex items-center gap-3 pb-8">
        <button onClick={handleSubmit} disabled={saving}
          className="btn-primary px-8 py-3 text-sm disabled:opacity-60 disabled:cursor-not-allowed">
          {saving
            ? <><svg className="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
                </svg>Saving…</>
            : <><svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                    d="M5 13l4 4L19 7"/>
                </svg>{isEdit ? 'Save Changes' : 'Create Form'}</>
          }
        </button>
        <button onClick={onCancel} className="btn-secondary px-6 py-3 text-sm">Cancel</button>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   FORM DETAIL (tracking links + submissions)
   ══════════════════════════════════════════════════════════════════════════════ */
function FormDetail({ formId, onBack, onEdit }) {
  const [data,        setData]        = useState(null)
  const [submissions, setSubmissions] = useState([])
  const [subTotal,    setSubTotal]    = useState(0)
  const [loading,     setLoading]     = useState(true)
  const [subLoading,  setSubLoading]  = useState(false)
  const [activeTab,   setActiveTab]   = useState('links')
  const [filterSrc,   setFilterSrc]   = useState('')
  const [newCamp, setNewCamp] = useState({ campaign_name: '', platform: 'linkedin' })
  const [addingCamp, setAddingCamp] = useState(false)
  const [showAddCamp, setShowAddCamp] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const d = await getFormDetail(formId)
      setData(d)
    } catch (err) { console.error(err) }
    finally { setLoading(false) }
  }, [formId])

  const loadSubs = useCallback(async (src = '') => {
    setSubLoading(true)
    try {
      const params = src ? { source: src, per_page: 100 } : { per_page: 100 }
      const d = await listSubmissions(formId, params)
      setSubmissions(d.submissions ?? [])
      setSubTotal(d.total ?? 0)
    } catch (err) { console.error(err) }
    finally { setSubLoading(false) }
  }, [formId])

  useEffect(() => { load() }, [load])
  useEffect(() => { if (activeTab === 'submissions') loadSubs(filterSrc) }, [activeTab, filterSrc, loadSubs])

  const handleAddCampaign = async () => {
    if (!newCamp.campaign_name.trim()) return
    setAddingCamp(true)
    try {
      await createCampaign(formId, newCamp)
      await load()
      setNewCamp({ campaign_name: '', platform: 'linkedin' })
      setShowAddCamp(false)
    } catch (err) { alert(err.message) }
    finally { setAddingCamp(false) }
  }

  if (loading) return (
    <div className="flex items-center justify-center py-20">
      <svg className="w-8 h-8 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
      </svg>
    </div>
  )

  if (!data) return <div className="text-center text-slate-400 py-20">Form not found.</div>

  const form      = data.form
  const campaigns = data.campaigns ?? []
  const publicUrl = `${FRONTEND_BASE}/f/${formId}`

  // build frontend tracking URLs
  const trackingLinks = campaigns.map(c => ({
    ...c,
    tracking_url: `${FRONTEND_BASE}/f/${formId}?source=${c.platform}&campaign_id=${c.campaign_id}`,
  }))

  return (
    <div className="max-w-4xl mx-auto">
      {/* header */}
      <div className="flex items-center gap-4 mb-6">
        <button onClick={onBack}
          className="w-9 h-9 flex items-center justify-center rounded-xl border border-slate-200
                     bg-white text-slate-500 hover:bg-slate-50 transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7"/>
          </svg>
        </button>
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-bold text-slate-900 truncate">{form.name}</h2>
          <p className="text-xs text-slate-400 mt-0.5">{form.category} · {data.submission_count} submission{data.submission_count !== 1 ? 's' : ''}</p>
        </div>
        <div className="flex items-center gap-2">
          <a href={publicUrl} target="_blank" rel="noopener noreferrer"
            className="btn-secondary px-4 py-2 text-xs gap-1.5">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14"/>
            </svg>
            Open Form
          </a>
          <button onClick={() => onEdit(form)}
            className="btn-secondary px-4 py-2 text-xs">Edit</button>
        </div>
      </div>

      {/* public URL */}
      <div className="crm-card p-4 mb-5 flex items-center gap-3">
        <span className="text-xs font-semibold text-slate-500 flex-shrink-0">Public URL:</span>
        <span className="text-xs text-indigo-600 truncate flex-1 font-mono">{publicUrl}</span>
        <CopyBtn text={publicUrl} />
      </div>

      {/* tabs */}
      <div className="flex gap-1 mb-5 bg-slate-100 p-1 rounded-xl w-fit">
        {[
          { id: 'links',       label: '🔗 Tracking Links' },
          { id: 'questions',   label: '❓ Questions' },
          { id: 'submissions', label: `📥 Submissions (${data.submission_count})` },
        ].map(t => (
          <button key={t.id} onClick={() => setActiveTab(t.id)}
            className={`px-4 py-2 rounded-lg text-xs font-semibold transition-all
                        ${activeTab === t.id ? 'bg-white shadow-sm text-slate-900' : 'text-slate-500 hover:text-slate-700'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {/* ── TRACKING LINKS ─────────────────────────────────────────── */}
      {activeTab === 'links' && (
        <div className="crm-card p-5">
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">Platform Tracking Links</h3>
            <button onClick={() => setShowAddCamp(s => !s)}
              className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold flex items-center gap-1">
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4"/>
              </svg>
              Add Campaign
            </button>
          </div>

          {showAddCamp && (
            <div className="mb-4 p-4 rounded-xl bg-indigo-50 border border-indigo-200 flex items-end gap-3 flex-wrap">
              <div className="flex flex-col gap-1 flex-1 min-w-[160px]">
                <label className="text-[11px] font-semibold text-slate-600">Campaign Name</label>
                <input type="text" value={newCamp.campaign_name}
                  onChange={e => setNewCamp(p => ({ ...p, campaign_name: e.target.value }))}
                  placeholder="e.g. Pune August 2026"
                  className="crm-input text-sm py-2" />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-[11px] font-semibold text-slate-600">Platform</label>
                <div className="relative">
                  <select value={newCamp.platform}
                    onChange={e => setNewCamp(p => ({ ...p, platform: e.target.value }))}
                    className="crm-input text-sm py-2 pr-8 appearance-none">
                    {PLATFORMS.map(p => <option key={p.id} value={p.id}>{p.icon} {p.label}</option>)}
                  </select>
                  <div className="pointer-events-none absolute inset-y-0 right-3 flex items-center">
                    <svg className="w-3.5 h-3.5 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                    </svg>
                  </div>
                </div>
              </div>
              <button onClick={handleAddCampaign} disabled={addingCamp}
                className="btn-primary px-4 py-2 text-xs disabled:opacity-60">
                {addingCamp ? 'Adding…' : 'Add'}
              </button>
              <button onClick={() => setShowAddCamp(false)} className="btn-secondary px-4 py-2 text-xs">Cancel</button>
            </div>
          )}

          <div className="space-y-3">
            {trackingLinks.map(c => {
              const plt = PLATFORMS.find(p => p.id === c.platform)
              return (
                <div key={c.campaign_id}
                  className={`rounded-xl border p-3.5 ${plt?.color ?? 'bg-slate-50 border-slate-200'}`}>
                  <div className="flex items-center gap-2 mb-1.5">
                    <span className="text-base">{plt?.icon ?? '🔗'}</span>
                    <span className="text-sm font-bold">{plt?.label ?? c.platform}</span>
                    <span className="text-[11px] text-slate-400 ml-1">· {c.campaign_name}</span>
                    <span className="ml-auto text-[10px] font-mono text-slate-400">{c.campaign_id}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-[11px] font-mono text-slate-600 truncate flex-1 bg-white/60 rounded px-2 py-1">
                      {c.tracking_url}
                    </span>
                    <CopyBtn text={c.tracking_url} />
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}

      {/* ── QUESTIONS ──────────────────────────────────────────────── */}
      {activeTab === 'questions' && (
        <div className="crm-card p-5">
          <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest mb-4">
            Questions ({form.questions?.length ?? 0})
          </h3>
          <div className="space-y-2">
            {(form.questions ?? []).sort((a,b) => a.display_order - b.display_order).map((q, i) => (
              <div key={q.question_id}
                className="flex items-start gap-3 px-4 py-3 rounded-xl border border-slate-100 bg-slate-50">
                <span className="text-xs font-mono text-slate-400 flex-shrink-0 mt-0.5 w-6">{i+1}.</span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-semibold text-slate-800">{q.label}</span>
                    {q.required && (
                      <span className="text-[10px] font-bold text-rose-500 bg-rose-50 border border-rose-200 px-1.5 py-0.5 rounded-full">Required</span>
                    )}
                    <span className="text-[11px] text-slate-400 bg-white border border-slate-200 px-2 py-0.5 rounded-full">
                      {QUESTION_TYPES.find(t => t.value === q.type)?.label ?? q.type}
                    </span>
                  </div>
                  {q.options?.length > 0 && (
                    <div className="flex flex-wrap gap-1 mt-1.5">
                      {q.options.map((o, oi) => (
                        <span key={oi} className="text-[10px] bg-white border border-slate-200 text-slate-500 px-2 py-0.5 rounded-full">{o.label}</span>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── SUBMISSIONS ────────────────────────────────────────────── */}
      {activeTab === 'submissions' && (
        <div className="crm-card p-5">
          <div className="flex items-center gap-3 mb-4 flex-wrap">
            <h3 className="text-xs font-bold text-slate-400 uppercase tracking-widest">
              Submissions ({subTotal})
            </h3>
            <div className="flex items-center gap-2 ml-auto">
              <span className="text-xs text-slate-500">Filter by source:</span>
              <div className="relative">
                <select value={filterSrc} onChange={e => setFilterSrc(e.target.value)}
                  className="text-xs border border-slate-200 rounded-lg px-3 py-1.5 bg-white text-slate-700
                             focus:outline-none focus:ring-2 focus:ring-indigo-400 appearance-none pr-8">
                  <option value="">All</option>
                  {PLATFORMS.map(p => <option key={p.id} value={p.id}>{p.icon} {p.label}</option>)}
                </select>
                <div className="pointer-events-none absolute inset-y-0 right-2 flex items-center">
                  <svg className="w-3 h-3 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7"/>
                  </svg>
                </div>
              </div>
              <button onClick={() => loadSubs(filterSrc)}
                className="btn-secondary px-3 py-1.5 text-xs">Refresh</button>
            </div>
          </div>

          {subLoading && (
            <div className="flex justify-center py-10">
              <svg className="w-6 h-6 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
              </svg>
            </div>
          )}

          {!subLoading && submissions.length === 0 && (
            <div className="text-center py-12">
              <p className="text-sm text-slate-400">No submissions yet{filterSrc ? ` from ${filterSrc}` : ''}.</p>
              <p className="text-xs text-slate-300 mt-1">Share your tracking links to start collecting leads.</p>
            </div>
          )}

          {!subLoading && submissions.map(sub => {
            const plt = PLATFORMS.find(p => p.id === sub.source)
            return (
              <div key={sub.submission_id}
                className="border border-slate-100 rounded-xl p-4 mb-3 bg-white">
                <div className="flex items-center gap-3 mb-3 flex-wrap">
                  <span className="text-sm">{plt?.icon ?? '🔗'}</span>
                  <span className={`text-xs font-semibold px-2.5 py-1 rounded-full border ${plt?.color ?? 'bg-slate-50 border-slate-200 text-slate-600'}`}>
                    {plt?.label ?? sub.source}
                  </span>
                  {sub.campaign_name && (
                    <span className="text-xs text-slate-500">· {sub.campaign_name}</span>
                  )}
                  <span className="ml-auto text-[11px] text-slate-400">{fmtDate(sub.submitted_at)}</span>
                  <span className="text-[10px] font-mono text-slate-300">{sub.submission_id}</span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {(sub.answers ?? []).map((ans, ai) => (
                    <div key={ai} className="flex flex-col gap-0.5 bg-slate-50 rounded-lg px-3 py-2">
                      <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">{ans.label}</span>
                      <span className="text-sm text-slate-800 font-medium">
                        {Array.isArray(ans.value) ? ans.value.join(', ') : (ans.value ?? '—')}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   FORMS LIST
   ══════════════════════════════════════════════════════════════════════════════ */
function FormsList({ onSelect, onCreate, onEdit, refreshKey }) {
  const [forms,   setForms]   = useState([])
  const [loading, setLoading] = useState(true)

  const load = useCallback(async () => {
    setLoading(true)
    try { const d = await listForms({ per_page: 100 }); setForms(d.forms ?? []) }
    catch (err) { console.error(err) }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load, refreshKey])

  const handleDelete = async (formId, name) => {
    if (!window.confirm(`Delete form "${name}"? This cannot be undone.`)) return
    try { await deleteForm(formId); load() }
    catch (err) { alert(err.message) }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <div>
          <h2 className="text-xl font-bold text-slate-900">Lead Forms</h2>
          <p className="text-xs text-slate-400 mt-0.5">Create forms and share them on LinkedIn, WhatsApp, X, and more</p>
        </div>
        <button onClick={onCreate} className="btn-primary px-5 py-2.5 text-sm">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M12 4v16m8-8H4"/>
          </svg>
          Create Form
        </button>
      </div>

      {loading && (
        <div className="flex justify-center py-16">
          <svg className="w-8 h-8 animate-spin text-indigo-400" fill="none" viewBox="0 0 24 24">
            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z"/>
          </svg>
        </div>
      )}

      {!loading && forms.length === 0 && (
        <div className="crm-card p-12 text-center">
          <div className="w-16 h-16 rounded-2xl bg-indigo-50 flex items-center justify-center mx-auto mb-4">
            <svg className="w-8 h-8 text-indigo-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
            </svg>
          </div>
          <p className="text-sm font-semibold text-slate-700">No forms yet</p>
          <p className="text-xs text-slate-400 mt-1 mb-4">Create your first lead collection form</p>
          <button onClick={onCreate} className="btn-primary px-6 py-2.5 text-sm">Create Form</button>
        </div>
      )}

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {forms.map(form => (
          <div key={form.form_id}
            className="crm-card p-5 hover:border-indigo-200 hover:shadow-md transition-all duration-150 cursor-pointer group"
            onClick={() => onSelect(form.form_id)}>
            <div className="flex items-start justify-between gap-2 mb-2">
              <h3 className="text-sm font-bold text-slate-800 group-hover:text-indigo-700 transition-colors leading-snug">
                {form.name}
              </h3>
              <span className={`flex-shrink-0 text-[11px] px-2 py-0.5 rounded-full font-semibold border
                ${form.status === 'active' ? 'bg-emerald-50 border-emerald-200 text-emerald-700' :
                  form.status === 'paused' ? 'bg-amber-50 border-amber-200 text-amber-700' :
                  'bg-slate-100 border-slate-200 text-slate-500'}`}>
                {form.status}
              </span>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              {CATEGORIES.find(c => c.label === form.category)?.icon ?? '📂'} {form.category}
            </p>
            {form.description && (
              <p className="text-xs text-slate-400 line-clamp-2 mb-3">{form.description}</p>
            )}
            <div className="flex items-center gap-3 text-[11px] text-slate-400 mb-3">
              <span>❓ {form.questions?.length ?? 0} questions</span>
              <span>·</span>
              <span>📥 {form.submission_count ?? 0} submissions</span>
            </div>
            <p className="text-[10px] text-slate-300">Created {fmtDate(form.created_at)}</p>

            <div className="flex gap-2 mt-3 pt-3 border-t border-slate-100">
              <button onClick={e => { e.stopPropagation(); onSelect(form.form_id) }}
                className="flex-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800 py-1.5 rounded-lg hover:bg-indigo-50 transition-colors">
                View Details
              </button>
              <button onClick={e => { e.stopPropagation(); onEdit(form) }}
                className="flex-1 text-xs font-semibold text-slate-600 hover:text-slate-800 py-1.5 rounded-lg hover:bg-slate-100 transition-colors">
                Edit
              </button>
              <button onClick={e => { e.stopPropagation(); handleDelete(form.form_id, form.name) }}
                className="text-xs font-semibold text-rose-400 hover:text-rose-700 px-3 py-1.5 rounded-lg hover:bg-rose-50 transition-colors">
                Delete
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   PAGE ROOT
   ══════════════════════════════════════════════════════════════════════════════ */
export default function FormLeads() {
  // view: 'list' | 'builder' | 'detail'
  const [view,       setView]       = useState('list')
  const [editForm,   setEditForm]   = useState(null)   // form object for edit
  const [detailId,   setDetailId]   = useState(null)   // form_id for detail
  const [refreshKey, setRefreshKey] = useState(0)
  const [successMsg, setSuccessMsg] = useState(null)   // post-create success with campaigns

  const handleCreate = () => { setEditForm(null); setView('builder') }
  const handleEdit   = (form) => { setEditForm(form); setView('builder') }
  const handleSelect = (formId) => { setDetailId(formId); setView('detail') }

  const handleSave = (form, campaigns, isNew) => {
    setRefreshKey(k => k + 1)
    if (isNew && campaigns) {
      setSuccessMsg({ form, campaigns })
      setView('detail')
      setDetailId(form.form_id)
    } else {
      setView('detail')
      setDetailId(form.form_id)
    }
  }

  return (
    <div className="min-h-screen bg-slate-100">
      {/* Top nav */}
      <header className="bg-white border-b border-slate-200 sticky top-0 z-30 shadow-sm">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="h-16 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-9 h-9 rounded-xl bg-violet-600 flex items-center justify-center shadow-md">
                <svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5}
                    d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2"/>
                </svg>
              </div>
              <div>
                <span className="text-base font-bold text-slate-900">Lead Forms</span>
                <span className="hidden sm:inline ml-2 text-xs text-slate-400">
                  — Social Lead Collection
                </span>
              </div>
            </div>
            <a href="/"
              className="inline-flex items-center gap-2 px-3.5 py-2 rounded-xl border border-slate-200
                         bg-white text-slate-600 hover:bg-slate-50 text-xs font-semibold transition-colors">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                  d="M13 10V3L4 14h7v7l9-11h-7z"/>
              </svg>
              Lead Generator
            </a>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {view === 'list' && (
          <FormsList
            onSelect={handleSelect}
            onCreate={handleCreate}
            onEdit={handleEdit}
            refreshKey={refreshKey}
          />
        )}

        {view === 'builder' && (
          <FormBuilder
            initialData={editForm}
            onSave={handleSave}
            onCancel={() => { setView(detailId ? 'detail' : 'list') }}
          />
        )}

        {view === 'detail' && detailId && (
          <FormDetail
            formId={detailId}
            onBack={() => setView('list')}
            onEdit={handleEdit}
          />
        )}
      </main>
    </div>
  )
}
