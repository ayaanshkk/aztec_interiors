-- Migration: Add additional_terms and additional_notes to financial document tables
-- Date: 2026-10-02
-- Description: Allows users to add optional custom terms and notes to quotes/invoices/proformas.
--   additional_terms: JSON array of strings (extra terms beyond the default two)
--   additional_notes: free-text notes for the document

ALTER TABLE "StreemLyne_MT"."Quotations"
  ADD COLUMN IF NOT EXISTS additional_terms TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS additional_notes TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_type TEXT DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS signature_image TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_text TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_name TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_date TEXT DEFAULT '';

ALTER TABLE "StreemLyne_MT"."Invoice_Master"
  ADD COLUMN IF NOT EXISTS additional_terms TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS additional_notes TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_type TEXT DEFAULT 'none',
  ADD COLUMN IF NOT EXISTS signature_image TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_text TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_name TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS signature_date TEXT DEFAULT '';

ALTER TABLE "StreemLyne_MT"."Payment_Terms_Master"
  ADD COLUMN IF NOT EXISTS additional_terms TEXT DEFAULT '',
  ADD COLUMN IF NOT EXISTS additional_notes TEXT DEFAULT '';
