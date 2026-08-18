/**
 * Dashboard.jsx
 * ─────────────
 * Overview page — answers "what's happening with my leads right now?"
 *
 * Sections:
 *   1. KPI cards  — Total Leads · New · Interested · Follow-ups Due
 *   2. Quick Actions — Generate Leads · View All Leads · Follow-ups
 *   3. Recent Activity — last 5 generation runs from /history
 *   4. Needs Attention — overdue + today follow-ups count
 *
 * All data comes from real API calls. No fake numbers.
 */

import { useState, useEffect, useCallback } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import Layout from '../components/Layout'
import {
  getLeadStatusCounts,
  getFollowUps,
  getHistory,
} from '../services/api'

/* ── helpers ──────────────────────────────────────────────────────────────── */
function fmtDate(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    const today    = new Date()
    const yesterday = new Date(today); yesterday.setDate(today.getDate() - 1)
    const ds = d.toDateString()
    if (ds === today.toDateString())     return 'Today'
    if (ds === yesterday.toDateString()) return 'Yesterday'
    return new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short' }).format(d)
  } catch { return '—' }
}

/* ── KPI card ──────────────────────────────────────────────────────────────── */
function KpiCard({ label, value, loading, accent, icon }) {
  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 flex items-center gap-4">
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0 ${accent}`}>
        {icon}
      </div>
      <div>
        {loading
          ? <div className="shimmer h-6 w-12 rounded mb-1" />
          : <p className="text-2xl font-bold text-slate-900 leading-none">{value ?? 0}</p>
        }
        <p className="text-xs text-slate-500 mt-1">{label}</p>
      </div>
    </div>
  )
}

/* ── Quick action button ───────────────────────────────────────────────────── */
function QuickAction({ to, label, description, icon, primary, state }) {
  return (
    <Link to={to} state={state}
      className={`flex items-center gap-4 p-4 rounded-xl border transition-all duration-150
                  ${primary
                    ? 'bg-indigo-600 border-indigo-600 text-white hover:bg-indigo-700 shadow-md'
                    : 'bg-white border-slate-200 text-slate-700 hover:border-indigo-300 hover:bg-indigo-50'}`}>
      <div className={`w-10 h-10 rounded-xl flex items-center justify-center flex-shrink-0
                       ${primary ? 'bg-white/20' : 'bg-slate-100'}`}>
        {icon}
      </div>
      <div>
        <p className={`text-sm font-semibold ${primary ? 'text-white' : 'text-slate-900'}`}>{label}</p>
        <p className={`text-xs mt-0.5 ${primary ? 'text-indigo-200' : 'text-slate-400'}`}>{description}</p>
      </div>
      <svg className={`w-4 h-4 ml-auto flex-shrink-0 ${primary ? 'text-white/60' : 'text-slate-300'}`}
           fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7"/>
      </svg>
    </Link>
  )
}

/* ── Recent run row ────────────────────────────────────────────────────────── */
function RunRow({ run }) {
  const statusCls = {
    completed: 'text-emerald-600 bg-emerald-50 border-emerald-200',
    running:   'text-sky-600 bg-sky-50 border-sky-200',
    failed:    'text-rose-600 bg-rose-50 border-rose-200',
  }[run.status] || 'text-slate-500 bg-slate-50 border-slate-200'

  return (
    <div className="flex items-center gap-4 py-3 border-b border-slate-100 last:border-0">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-semibold text-slate-800 truncate">{run.category}</p>
        <p className="text-xs text-slate-400 mt-0.5">
          {[run.district, run.state].filter(Boolean).join(', ') || 'India'}
          {' · '}{run.requested_count} requested
        </p>
      </div>
      <div className="text-right flex-shrink-0">
        <p className="text-sm font-bold text-slate-700">{run.generated_count ?? '—'}</p>
        <p className="text-[10px] text-slate-400">found</p>
      </div>
      <div className="w-20 text-right flex-shrink-0">
        <span className={`inline-flex items-center px-2 py-0.5 rounded-full border text-[10px] font-semibold ${statusCls}`}>
          {run.status === 'running' ? 'Running' : run.status === 'completed' ? 'Done' : 'Failed'}
        </span>
        <p className="text-[10px] text-slate-400 mt-1">{fmtDate(run.started_at)}</p>
      </div>
    </div>
  )
}

/* ══════════════════════════════════════════════════════════════════════════════
   PAGE
   ══════════════════════════════════════════════════════════════════════════════ */
export default function Dashboard() {
  const navigate = useNavigate()

  const [counts,          setCounts]          = useState(null)
  const [countsLoading,   setCountsLoading]   = useState(true)
  const [followUps,       setFollowUps]       = useState(null)
  const [followUpsLoading,setFollowUpsLoading]= useState(true)
  const [runs,            setRuns]            = useState([])
  const [runsLoading,     setRunsLoading]     = useState(true)
  const [refreshTick,     setRefreshTick]     = useState(0)

  const loadAll = useCallback(async () => {
    setCountsLoading(true)
    setFollowUpsLoading(true)
    setRunsLoading(true)

    const [countsRes, followUpsRes, runsRes] = await Promise.allSettled([
      getLeadStatusCounts(null, true),
      getFollowUps(null),
      getHistory({ per_page: 5 }),
    ])

    if (countsRes.status === 'fulfilled') setCounts(countsRes.value.counts ?? {})
    setCountsLoading(false)

    if (followUpsRes.status === 'fulfilled') setFollowUps(followUpsRes.value)
    setFollowUpsLoading(false)

    if (runsRes.status === 'fulfilled') setRuns(runsRes.value.runs?.slice(0, 5) ?? [])
    setRunsLoading(false)
  }, [])

  useEffect(() => { loadAll() }, [loadAll, refreshTick])

  const overdueCount = (followUps?.overdue?.length ?? 0) + (followUps?.today?.length ?? 0)

  return (
    <Layout
      followUpRefreshTick={refreshTick}
      onOpenFollowUps={() => navigate('/follow-ups')}
      onNavigateToLead={(lead) => navigate('/', { state: { scrollToLead: lead.id ?? lead._id } })}
    >
      <div className="max-w-5xl mx-auto px-4 sm:px-6 lg:px-8 py-8">

        {/* ── Page header ─────────────────────────────────────────────── */}
        <div className="mb-8">
          <h1 className="text-xl font-bold text-slate-900">Dashboard</h1>
          <p className="text-sm text-slate-500 mt-1">Here's what's happening with your leads today.</p>
        </div>

        {/* ── KPI cards ───────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 mb-8">
          <KpiCard
            label="Total Leads"
            value={counts?.total}
            loading={countsLoading}
            accent="bg-indigo-50"
            icon={<svg className="w-5 h-5 text-indigo-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 10h16M4 14h16M4 18h16"/></svg>}
          />
          <KpiCard
            label="New Leads"
            value={counts?.new}
            loading={countsLoading}
            accent="bg-sky-50"
            icon={<svg className="w-5 h-5 text-sky-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4"/></svg>}
          />
          <KpiCard
            label="Interested"
            value={counts?.interested}
            loading={countsLoading}
            accent="bg-emerald-50"
            icon={<svg className="w-5 h-5 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7"/></svg>}
          />
          <KpiCard
            label="Follow-ups Due"
            value={overdueCount}
            loading={followUpsLoading}
            accent={overdueCount > 0 ? 'bg-amber-50' : 'bg-slate-50'}
            icon={<svg className={`w-5 h-5 ${overdueCount > 0 ? 'text-amber-600' : 'text-slate-400'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>}
          />
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Left column — Quick Actions + Needs Attention */}
          <div className="lg:col-span-1 space-y-6">

            {/* ── Quick Actions ──────────────────────────────────────── */}
            <div>
              <h2 className="text-sm font-semibold text-slate-700 mb-3">Quick Actions</h2>
              <div className="space-y-2.5">
                <QuickAction
                  to="/generate"
                  label="Generate Leads"
                  description="Find new companies matching your criteria"
                  primary
                  icon={<svg className="w-5 h-5 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M13 10V3L4 14h7v7l9-11h-7z"/></svg>}
                />
                <QuickAction
                  to="/"
                  state={{ todayFilter: true }}
                  label="Today's Leads"
                  description={counts?.new ? `${counts.new} new leads` : 'Leads generated today'}
                  icon={<svg className="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>}
                />
                <QuickAction
                  to="/follow-ups"
                  label="Follow-ups"
                  description={overdueCount > 0 ? `${overdueCount} need attention` : 'View scheduled follow-ups'}
                  icon={<svg className="w-5 h-5 text-slate-500" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z"/></svg>}
                />
              </div>
            </div>

            {/* ── Needs Attention ────────────────────────────────────── */}
            {!followUpsLoading && overdueCount > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded-xl p-4">
                <h2 className="text-sm font-semibold text-amber-800 mb-3">Needs Your Attention</h2>
                <div className="space-y-2">
                  {(followUps?.overdue?.length ?? 0) > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-amber-700">Overdue follow-ups</span>
                      <span className="text-sm font-bold text-rose-600">{followUps.overdue.length}</span>
                    </div>
                  )}
                  {(followUps?.today?.length ?? 0) > 0 && (
                    <div className="flex items-center justify-between">
                      <span className="text-sm text-amber-700">Due today</span>
                      <span className="text-sm font-bold text-amber-700">{followUps.today.length}</span>
                    </div>
                  )}
                </div>
                <Link to="/follow-ups"
                  className="mt-3 inline-flex items-center gap-1 text-xs font-semibold
                             text-amber-700 hover:text-amber-900 transition-colors">
                  View follow-ups →
                </Link>
              </div>
            )}
          </div>

          {/* Right column — Recent Activity */}
          <div className="lg:col-span-2">
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-4">
                <h2 className="text-sm font-semibold text-slate-700">Recent Lead Generation</h2>
                <Link to="/history"
                  className="text-xs text-indigo-600 hover:text-indigo-800 font-medium transition-colors">
                  View history →
                </Link>
              </div>

              {runsLoading && (
                <div className="space-y-3">
                  {[1,2,3].map(i => (
                    <div key={i} className="flex items-center gap-4 py-3 border-b border-slate-100">
                      <div className="flex-1"><div className="shimmer h-4 w-32 rounded mb-1.5"/><div className="shimmer h-3 w-48 rounded"/></div>
                      <div className="shimmer h-4 w-8 rounded"/>
                      <div className="shimmer h-5 w-20 rounded-full"/>
                    </div>
                  ))}
                </div>
              )}

              {!runsLoading && runs.length === 0 && (
                <div className="text-center py-10">
                  <svg className="w-10 h-10 text-slate-300 mx-auto mb-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z"/>
                  </svg>
                  <p className="text-sm text-slate-500">No generation runs yet.</p>
                  <p className="text-xs text-slate-400 mt-1">
                    <Link to="/generate" className="text-indigo-600 hover:underline">Generate your first leads</Link> to see activity here.
                  </p>
                </div>
              )}

              {!runsLoading && runs.length > 0 && (
                <div>
                  {runs.map(run => <RunRow key={run.run_id} run={run} />)}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </Layout>
  )
}
