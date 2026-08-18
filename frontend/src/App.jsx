/**
 * App.jsx
 * ───────
 * Route configuration for LeadCRM.
 *
 * Primary routes (use shared Layout with clean nav):
 *   /dashboard    → Dashboard
 *   /generate     → GenerateLeads
 *   /             → Leads (main CRM workspace)
 *   /follow-ups   → FollowUps
 *   /history      → History
 *
 * Secondary routes (feature pages, use own headers that include Layout):
 *   /social-leads → SocialLeads
 *   /forms        → FormLeads
 *   /origami      → OrigamiEnrichment (People Enrichment)
 *
 * Public routes (no nav — standalone pages):
 *   /f/:form_id   → PublicForm
 *
 * Legacy fallback:
 *   /legacy       → LeadGeneration (old monolithic page, kept as safety net)
 *   *             → redirects to /dashboard
 */

import { Routes, Route, Navigate } from 'react-router-dom'

// New clean pages
import Dashboard       from './pages/Dashboard'
import GenerateLeads   from './pages/GenerateLeads'
import Leads           from './pages/Leads'
import FollowUps       from './pages/FollowUps'
import History         from './pages/History'

// Secondary / "More" pages
import SocialLeads       from './pages/SocialLeads'
import FormLeads         from './pages/FormLeads'
import OrigamiEnrichment from './pages/OrigamiEnrichment'

// Public standalone page (no nav)
import PublicForm from './pages/PublicForm'

// Legacy monolithic page — kept as safety net, accessible at /legacy
import LeadGeneration from './pages/LeadGeneration'

export default function App() {
  return (
    <Routes>
      {/* ── Primary navigation ─────────────────────────────────────── */}
      <Route path="/dashboard"   element={<Dashboard />} />
      <Route path="/generate"    element={<GenerateLeads />} />
      <Route path="/"            element={<Leads />} />
      <Route path="/follow-ups"  element={<FollowUps />} />
      <Route path="/history"     element={<History />} />

      {/* ── Secondary / More ───────────────────────────────────────── */}
      <Route path="/social-leads" element={<SocialLeads />} />
      <Route path="/forms"        element={<FormLeads />} />
      <Route path="/origami"      element={<OrigamiEnrichment />} />

      {/* ── Public form (no nav) ───────────────────────────────────── */}
      <Route path="/f/:form_id"   element={<PublicForm />} />

      {/* ── Legacy fallback (old monolithic page, kept as safety net) ─ */}
      <Route path="/legacy"       element={<LeadGeneration />} />

      {/* ── 404 → redirect to dashboard ────────────────────────────── */}
      <Route path="*"             element={<Navigate to="/dashboard" replace />} />
    </Routes>
  )
}
