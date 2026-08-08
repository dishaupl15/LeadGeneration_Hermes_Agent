import mongoose from 'mongoose'

const { Schema, model } = mongoose

/**
 * Lead Schema
 *
 * Represents a single B2B CRM lead generated for a given industry / city.
 *
 * Field notes
 * ───────────
 *  emails  – Array because a company often has multiple contacts
 *            (info@, sales@, support@ …)
 *  phones  – Array for the same reason (landline + mobile + WhatsApp)
 *  createdAt – managed automatically by Mongoose timestamps; no need to
 *              set it manually when creating a document.
 */
const leadSchema = new Schema(
  {
    // ── Company identity ──────────────────────────────────────────────────────
    company_name: {
      type:     String,
      required: [true, 'company_name is required'],
      trim:     true,
    },

    website: {
      type:    String,
      trim:    true,
      default: '',
    },

    // ── Contact arrays ────────────────────────────────────────────────────────
    emails: {
      type:    [String],
      default: [],
    },

    phones: {
      type:    [String],
      default: [],
    },

    // ── Location ──────────────────────────────────────────────────────────────
    address: {
      type:    String,
      trim:    true,
      default: '',
    },

    city: {
      type:    String,
      trim:    true,
      default: '',
    },

    state: {
      type:    String,
      trim:    true,
      default: '',
    },

    country: {
      type:    String,
      trim:    true,
      default: '',
    },
  },
  {
    // Automatically adds `createdAt` and `updatedAt` fields managed by Mongoose
    timestamps: true,

    // Clean JSON output — removes __v from API responses
    toJSON: {
      virtuals: true,
      versionKey: false,
      transform: (_doc, ret) => {
        ret.id = ret._id
        delete ret._id
        return ret
      },
    },
  }
)

// ── Indexes ───────────────────────────────────────────────────────────────────
// Speed up the most common query patterns.
leadSchema.index({ company_name: 1 })
leadSchema.index({ city: 1 })
leadSchema.index({ country: 1 })
leadSchema.index({ createdAt: -1 })   // latest-first queries

const Lead = model('Lead', leadSchema)

export default Lead
