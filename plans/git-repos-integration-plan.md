# Git Repository Integration Plan - EXACT COMMANDS

## Scenario: Option 2 + Option 3 (Frontend first, then Full Backend Merge)

---

## STEP 1: Frontend Repository (A:\aztec-interior)

Run these commands in **PowerShell** or **CMD** in the `A:\aztec-interior` folder:

```powershell
# Step 1.1: Navigate to frontend folder
cd A:\aztec-interior

# Step 1.2: Stage all changes
git add .

# Step 1.3: Commit with descriptive message
git commit -m "feat(frontend): update quotes, customers pages and API integration

- Update quote pages with new reference format support
- Update customer pages with improved data handling  
- Add notification context improvements
- Update API utilities for better integration"

# Step 1.4: Push to main
git push origin main
```

---

## STEP 2: Backend Repository (A:\aztec_interiors)

Run these commands in **PowerShell** or **CMD** in the `A:\aztec_interiors` folder:

```powershell
# Step 2.1: Navigate to backend folder
cd A:\aztec_interiors

# Step 2.2: Stage the quote numbering file
git add backend/routes/quotation_routes.py

# Step 2.3: Commit with descriptive message
git commit -m "feat(quotations): implement systematic quote numbering AZT-YYYY-{CAT}-{SEQ}

- Add get_category_code() helper to extract category from notes/parameters
- Add generate_quote_reference() for sequential quote IDs
- Replace random/timestamp IDs with format: AZT-2026-K-001
- Support categories: K=Kitchen, B=Bedroom, W=Wardrobe, R=Remedial, O=Other
- Update handle_quotations POST endpoint to use new format
- Update generate_quote_from_checklist to use category from checklist_type
- Sequence auto-increments per year/category combination"

# Step 2.4: Push feature branch to remote
git push origin feature/quote-generation-fix

# Step 2.5: Switch to main branch
git checkout main

# Step 2.6: Pull latest main (in case there are remote changes)
git pull origin main

# Step 2.7: Merge feature branch into main
git merge feature/quote-generation-fix

# Step 2.8: Push main with merged changes
git push origin main
```

---

## Summary of What Gets Committed

### Frontend (Main Branch):
- `.env.development` and `.env.local` configs
- `next.config.mjs`
- All quote and customer page updates
- API and notification improvements

### Backend (Main Branch):
- `backend/routes/quotation_routes.py` - Quote numbering implementation with format `AZT-YYYY-{CAT}-{SEQ}`

---

## After Running These Commands:

Both repositories will have:
- All changes pushed to remote
- Main branches updated with the new quote numbering system
- Quote IDs will now be: `AZT-2026-K-001`, `AZT-2026-B-015`, etc.

---

## If You Get Merge Conflicts:

1. **Don't panic** - resolve conflicts manually
2. Edit the conflicting files to keep what you need
3. After resolving:
   ```powershell
- [ ] Verify frontend builds without errors (`npm run build`)
- [ ] Test quote creation with new format
- [ ] Review changed files for sensitive data (env files)

---

## Notes

1. **Quote Numbering Format**: New quotes will use format `AZT-YYYY-{CAT}-{SEQ}` (e.g., `AZT-2026-K-001`)
2. **Existing Quotes**: Old quotes retain their existing reference numbers
3. **Category Detection**: Kitchen, Bedroom, Wardrobe, Remedial automatically detected from notes/checklist

---

## Next Steps After This Plan

Once you approve this plan, I can execute the git commands in the Code mode to:
1. Commit the backend changes
2. Push to remote
3. Merge to main (if you choose that option)
