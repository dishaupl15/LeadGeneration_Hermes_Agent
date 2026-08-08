import mongoose from 'mongoose'
import 'dotenv/config'

/**
 * Connects to MongoDB using the URI defined in the MONGODB_URI environment variable.
 *
 * Call this once at application startup (e.g. in server.js / app.js).
 * Subsequent calls are safe — mongoose reuses the existing connection.
 *
 * @returns {Promise<void>}
 */
const connectDB = async () => {
  const uri = process.env.MONGODB_URI

  if (!uri) {
    console.error('❌  MONGODB_URI is not defined in your .env file')
    process.exit(1)
  }

  try {
    await mongoose.connect(uri, {
      // Suppress deprecation warnings on current Mongoose 7+/8+ — these are
      // the recommended defaults; kept explicit for clarity.
      serverSelectionTimeoutMS: 5000,   // fail fast if MongoDB is unreachable
    })

    console.log(`MongoDB Connected: ${mongoose.connection.host}`)
  } catch (error) {
    console.error(`❌  MongoDB connection failed: ${error.message}`)
    process.exit(1)    // exit so the process manager (PM2, Docker) can restart
  }
}

export default connectDB
