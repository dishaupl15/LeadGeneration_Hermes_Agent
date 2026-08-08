import 'dotenv/config'
import express from 'express'
import connectDB from './config/database.js'

const app = express()
const PORT = process.env.PORT || 5000

// ── Middleware ────────────────────────────────────────────────────────────────
app.use(express.json())

// ── Health check ──────────────────────────────────────────────────────────────
app.get('/health', (_req, res) => {
  res.json({ status: 'ok' })
})

// ── Bootstrap ─────────────────────────────────────────────────────────────────
// Connect to MongoDB first; only start listening once the connection succeeds.
const start = async () => {
  await connectDB()

  app.listen(PORT, () => {
    console.log(`🚀  Server running on http://localhost:${PORT}`)
  })
}

start()
