import { Routes, Route } from 'react-router-dom'
import LeadGeneration from './pages/LeadGeneration'
import FormLeads from './pages/FormLeads'
import PublicForm from './pages/PublicForm'
import SocialLeads from './pages/SocialLeads'

export default function App() {
  return (
    <Routes>
      {/* Main CRM */}
      <Route path="/"              element={<LeadGeneration />} />

      {/* Form builder admin */}
      <Route path="/forms"         element={<FormLeads />} />

      {/* Social leads dashboard */}
      <Route path="/social-leads"  element={<SocialLeads />} />

      {/* Public form (from tracking links) */}
      <Route path="/f/:form_id"    element={<PublicForm />} />

      {/* 404 fallback */}
      <Route path="*"              element={<LeadGeneration />} />
    </Routes>
  )
}
