# Door Style Price Implementation - Testing Instructions

## Summary of Changes

This implementation adds automatic price calculation based on door style to the quotation system. The system now uses different prices for different door styles (slab, vinyl, glazed, shaker).

## Changes Made

### 1. Database Model ([`models.py`](../aztec_interiors/backend/models.py))

Added four new price fields to the `PriceListItem` model:
- `basic_slab_price` - Price for slab doors
- `vinyl_doors_price` - Price for vinyl doors
- `acrylic_gloss_matt_price` - Price for acrylic/gloss/matt doors
- `black_glass_price` - Price for black glass doors

### 2. Database Migration ([`migrations/add_door_style_prices.sql`](../aztec_interiors/backend/migrations/add_door_style_prices.sql))

Created SQL migration script to add the new columns to the database.

### 3. Backend Logic ([`quotation_routes.py`](../aztec_interiors/backend/routes/quotation_routes.py))

Modified the `find_price` function to:
- Accept a `door_style` parameter
- Map door styles to price fields:
  - 'slab' → `basic_slab_price`
  - 'vinyl' → `vinyl_doors_price`
  - 'glazed' → `black_glass_price`
  - 'shaker' → `acrylic_gloss_matt_price`
  - 'N/A' → `base_price`
- Return the correct price based on the door style

Updated `extract_checklist_items` to pass `door_style` to `find_price` for both main and additional doors.

## Testing Instructions

### Step 1: Run the Database Migration

Execute the SQL migration script to add the new columns to the database:

```bash
cd ../aztec_interiors/backend
sqlite3 local.db < migrations/add_door_style_prices.sql
```

Or if using PostgreSQL:
```bash
psql -U your_username -d your_database -f migrations/add_door_style_prices.sql
```

### Step 2: Populate Door Style Prices

The price list data already contains door style prices. You need to import this data into the new columns. Run the price import script:

```bash
python setup_appliance_catalog.py
```

Or manually update the database with the door style prices from the price list data.

### Step 3: Restart the Backend Server

Stop the current backend server and restart it to apply the model changes:

```bash
# Stop the server (Ctrl+C)
# Then restart:
python app.py
```

### Step 4: Test the Automatic Price Calculation

1. **Open the checklist form**
2. **Set Door Type to "Slab"**
3. **Save the form**
4. **Generate a new quote**
5. **Check the price** - It should now use the `basic_slab_price` from the database

6. **Test with different door styles:**
   - Change Door Type to "Vinyl" → Should use `vinyl_doors_price`
   - Change Door Type to "Glazed" → Should use `black_glass_price`
   - Change Door Type to "Shaker" → Should use `acrylic_gloss_matt_price`

### Step 5: Verify the Logs

Check the backend logs for the following messages:
- `🔍 Searching for: 'door' in category 'bedroom' (door_style: 'slab')`
- `💰 Using price field: 'basic_slab_price' for door_style: 'slab'`
- `✅ Found match: 400mm wide robe - £85.03 (400mm) using basic_slab_price`

## Expected Behavior

- When door_style is "slab", the system should use `basic_slab_price`
- When door_style is "vinyl", the system should use `vinyl_doors_price`
- When door_style is "glazed", the system should use `black_glass_price`
- When door_style is "shaker", the system should use `acrylic_gloss_matt_price`
- If the door style price is not set, the system should fall back to `base_price`

## Troubleshooting

### Issue: Prices are still the same for all door styles

**Solution:** Make sure the database migration was run successfully and the door style prices were populated in the database.

### Issue: Backend server won't start

**Solution:** Make sure the database migration was run before restarting the server. The model changes require the new columns to exist in the database.

### Issue: "No price found for: door" error

**Solution:** Check that the price list items have the door style prices populated. Run the price import script again.

## Price Mapping Reference

| Door Style | Price Field | Example Price (40R) |
|------------|-------------|----------------------|
| slab | basic_slab_price | £85.03 |
| vinyl | vinyl_doors_price | £159.86 |
| glazed | black_glass_price | £453.44 |
| shaker | acrylic_gloss_matt_price | £127.55 |
| N/A | base_price | £197.34 |