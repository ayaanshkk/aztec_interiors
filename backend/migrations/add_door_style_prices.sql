-- Migration: Add door style price fields to price_list_items table
-- Date: 2025-02-11
-- Description: Add columns for different door style prices to support automatic price calculation

-- Add door style price columns
ALTER TABLE price_list_items 
ADD COLUMN basic_slab_price NUMERIC(10, 2);

ALTER TABLE price_list_items 
ADD COLUMN vinyl_doors_price NUMERIC(10, 2);

ALTER TABLE price_list_items 
ADD COLUMN acrylic_gloss_matt_price NUMERIC(10, 2);

ALTER TABLE price_list_items 
ADD COLUMN black_glass_price NUMERIC(10, 2);

-- Create index on door style price columns for faster queries
CREATE INDEX idx_price_list_items_basic_slab_price ON price_list_items(basic_slab_price);
CREATE INDEX idx_price_list_items_vinyl_doors_price ON price_list_items(vinyl_doors_price);
CREATE INDEX idx_price_list_items_acrylic_gloss_matt_price ON price_list_items(acrylic_gloss_matt_price);
CREATE INDEX idx_price_list_items_black_glass_price ON price_list_items(black_glass_price);
