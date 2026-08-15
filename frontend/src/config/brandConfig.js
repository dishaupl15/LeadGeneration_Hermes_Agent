/**
 * brandConfig.js
 * ──────────────
 * Central company branding configuration for all public-facing forms.
 *
 * HOW TO UPDATE BRANDING:
 *   Edit this file only — every generated public form inherits these values automatically.
 *
 * HOW TO REPLACE THE LOGO:
 *   1. Drop your new logo file into  frontend/public/
 *   2. Update `logoSrc` below to  '/your-logo-filename.png'
 *
 * HOW TO CHANGE COMPANY NAME / DESCRIPTION:
 *   Edit `name`, `tagline`, and `description` below.
 *
 * HOW TO CHANGE ACCENT COLOUR:
 *   Edit the `accent*` fields using Tailwind arbitrary-value classes, e.g. 'bg-[#1a56db]'
 */

export const BRAND = {
  // ── Identity ──────────────────────────────────────────────────────────────
  name:        'Pratap AI Innovations',
  tagline:     'The AI layer between strategy and execution.',
  description: 'We help leadership teams adopt AI across their organisations — with strategy, systems, and enablement that actually works.',

  // ── Contact & web ─────────────────────────────────────────────────────────
  website:      'https://pratap.ai',
  contactEmail: 'hello@pratap.ai',
  location:     'India',
  linkedin:     'https://www.linkedin.com/company/pratap-ai/',

  // ── Logo ──────────────────────────────────────────────────────────────────
  // Relative to the public/ folder — works in both dev and production builds.
  // Never use a local Windows path here.
  logoSrc:  '/pratap-ai-logo.png',
  logoAlt:  'Pratap AI Innovations',
  logoMaxH: 56,   // px — logo is displayed at this height, aspect ratio preserved

  // ── Privacy & legal ───────────────────────────────────────────────────────
  privacyPolicyUrl: 'https://pratap.ai/privacy',   // set to '' to hide the link

  // ── Accent colours (Tailwind arbitrary-value classes) ─────────────────────
  // Used for the submit button, focus rings, header accent bar, and other highlights.
  // Change these without touching component code to match a new brand palette.
  accentBg:          'bg-[#0F172A]',          // submit button background  (dark navy)
  accentHoverBg:     'hover:bg-[#1e2d47]',    // submit button hover
  accentRing:        'focus:ring-[#3b5bdb]',  // input focus ring
  accentBorder:      'focus:border-[#3b5bdb]',
  accentText:        'text-[#0F172A]',
  accentBarBg:       'bg-[#0F172A]',          // top accent bar on the form card
}
