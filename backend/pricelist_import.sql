-- ============================================================================
-- BEDROOM PRICE LIST IMPORT
-- Generated from: KBB Pricelist 2.xlsx
-- Total items: 44
-- ============================================================================

-- Delete existing bedroom items (optional - comment out if you want to keep existing)
-- DELETE FROM price_list_items WHERE category = 'bedroom';

-- Insert bedroom price list items
INSERT INTO price_list_items (category, item_code, item_name, description, base_price, width, height, depth, subcategory, dimension_based, active)
VALUES
    ('bedroom', '40R', '400mm wide robe', '400mm wide robe (W400mm x H2160mm x D570mm)', 197.33999999999997, 400, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '50R', '500mm wide rode', '500mm wide rode (W500mm x H2160mm x D570mm)', 199.87, 500, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '60R', '600mm wide robe', '600mm wide robe (W600mm x H2160mm x D570mm)', 202.39999999999998, 600, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '80R', '800mm wide robe', '800mm wide robe (W800mm x H2160mm x D570mm)', 211.82999999999998, 800, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '100R', '1000mm wide robe', '1000mm wide robe (W1000mm x H2160mm x D570mm)', 216.66, 1000, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '120R', '1200mm wide robe', '1200mm wide robe (W1200mm x H2160mm x D570mm)', 221.48999999999998, 1200, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '80RC', '800mm wide corner robe', '800mm wide corner robe (W800mm x H2160mm x D570mm)', 257.59999999999997, 800, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '90RC', '900mm wide corner robe', '900mm wide corner robe (W900mm x H2160mm x D570mm)', 262.2, 900, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '100RC', '1000mm wide corner robe', '1000mm wide corner robe (W1000mm x H2160mm x D570mm)', 266.79999999999995, 1000, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '120RC', '1200mm wide corner robe', '1200mm wide corner robe (W1200mm x H2160mm x D570mm)', 271.4, 1200, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', '90RDCNR', 'diagonal corner robe (496mm door)', 'diagonal corner robe (496mm door) (H2160mm x D570mm)', 340.4, NULL, 2160, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', 'WDS', 'Standard Door Split', 'Standard Door Split', 114.99999999999999, NULL, NULL, NULL, 'Wardrobes', FALSE, TRUE),
    ('bedroom', 'IDRW', 'x1 standard Internal drawer', 'x1 standard Internal drawer (H120mm x D570mm)', 50.599999999999994, NULL, 120, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', 'SCIDRW', 'x1 Internal softclose drawer', 'x1 Internal softclose drawer (H120mm x D570mm)', 138.0, NULL, 120, 570, 'Wardrobes', TRUE, TRUE),
    ('bedroom', 'SDSC1', 'Sliding Door (Single Colour)', 'Sliding Door (Single Colour) (W1000mm x H2160mm x D660mm)', 390.99999999999994, 1000, 2160, 660, 'Wardrobes', TRUE, TRUE),
    ('bedroom', 'SDFM1', 'Sliding Door - Full Mirror', 'Sliding Door - Full Mirror (W1000mm x H2160mm x D660mm)', 390.99999999999994, 1000, 2160, 660, 'Wardrobes', TRUE, TRUE),
    ('bedroom', 'SDSC3', 'Sliding Door - x3 Split Colour', 'Sliding Door - x3 Split Colour (W1000mm x H2160mm x D660mm)', 459.99999999999994, 1000, 2160, 660, 'Wardrobes', TRUE, TRUE),
    ('bedroom', 'SDS', 'Sliding Door - Extra Split', 'Sliding Door - Extra Split', 46.0, NULL, NULL, NULL, 'Wardrobes', FALSE, TRUE),
    ('bedroom', '40RLP', 'linen press 1495mm door + 3 x 215mm drawers 400mm wide', 'linen press 1495mm door + 3 x 215mm drawers 400mm wide (W400mm x H2160mm x D570mm)', 292.09999999999997, 400, 2160, 570, 'Linen Press', TRUE, TRUE),
    ('bedroom', '50RLP', 'linen press 1495mm door + 3 x 215mm drawers 500mm wide', 'linen press 1495mm door + 3 x 215mm drawers 500mm wide (W500mm x H2160mm x D570mm)', 294.4, 500, 2160, 570, 'Linen Press', TRUE, TRUE),
    ('bedroom', '60RLP', 'linen press 1495mm door + 3 x 215mm drawers 600mm wide', 'linen press 1495mm door + 3 x 215mm drawers 600mm wide (W600mm x H2160mm x D570mm)', 296.7, 600, 2160, 570, 'Linen Press', TRUE, TRUE),
    ('bedroom', '80RLP', 'linen press 1495mm door + 3 x 215mm drawers 800mm wide', 'linen press 1495mm door + 3 x 215mm drawers 800mm wide (W800mm x H2160mm x D570mm)', 312.79999999999995, 800, 2160, 570, 'Linen Press', TRUE, TRUE),
    ('bedroom', '100RLP', 'linen press 1495mm door + 3 x 215mm drawers 1000mm wide', 'linen press 1495mm door + 3 x 215mm drawers 1000mm wide (W1000mm x H2160mm x D570mm)', 315.09999999999997, 1000, 2160, 570, 'Linen Press', TRUE, TRUE),
    ('bedroom', '40BRS', '540mm high x 560mm deep deep bridging unit 400mm wide', '540mm high x 560mm deep deep bridging unit 400mm wide (W400mm x H540mm x D570mm)', 82.8, 400, 540, 570, 'Wall Units', TRUE, TRUE),
    ('bedroom', '50BRS', '540mm high x 560mm deep deep bridging unit 500mm wide', '540mm high x 560mm deep deep bridging unit 500mm wide (W500mm x H540mm x D570mm)', 87.39999999999999, 500, 540, 570, 'Wall Units', TRUE, TRUE),
    ('bedroom', '60BRS', '540mm high x 560mm deep deep bridging unit 600mm wide', '540mm high x 560mm deep deep bridging unit 600mm wide (W600mm x H540mm x D570mm)', 92.0, 600, 540, 570, 'Wall Units', TRUE, TRUE),
    ('bedroom', '80BRS', '540mm high x 560mm deep deep bridging unit 800mm wide', '540mm high x 560mm deep deep bridging unit 800mm wide (W800mm x H540mm x D570mm)', 103.49999999999999, 800, 540, 570, 'Wall Units', TRUE, TRUE),
    ('bedroom', '100BRS', '540mm high x 560mm deep deep bridging unit 1000mm wide', '540mm high x 560mm deep deep bridging unit 1000mm wide (W1000mm x H540mm x D570mm)', 108.1, 1000, 540, 570, 'Wall Units', TRUE, TRUE),
    ('bedroom', '120BRS', '540mm high x 560mm deep deep bridging unit 1200mm wide', '540mm high x 560mm deep deep bridging unit 1200mm wide (W1200mm x H540mm x D570mm)', 112.69999999999999, 1200, 540, 570, 'Wall Units', TRUE, TRUE),
    ('bedroom', '403BDRW', '760mm high x 490mm deep + 3 x 215mm drawers 400mm wide', '760mm high x 490mm deep + 3 x 215mm drawers 400mm wide (W400mm x H760mm x D490mm)', 188.6, 400, 760, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '503BDRW', '760mm high x 490mm deep + 3 x 215mm drawers 500mm wide', '760mm high x 490mm deep + 3 x 215mm drawers 500mm wide (W500mm x H760mm x D490mm)', 193.2, 500, 760, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '603BDRW', '760mm high x 490mm deep + 3 x 215mm drawers 600mm wide', '760mm high x 490mm deep + 3 x 215mm drawers 600mm wide (W600mm x H760mm x D490mm)', 197.79999999999998, 600, 760, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '803BDRW', '760mm high x 490mm deep + 3 x 215mm drawers 800mm wide', '760mm high x 490mm deep + 3 x 215mm drawers 800mm wide (W800mm x H760mm x D490mm)', 206.99999999999997, 800, 760, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '1003BDRW', '760mm high x 490mm deep + 3 x 215mm drawers 1000mm wide', '760mm high x 490mm deep + 3 x 215mm drawers 1000mm wide (W1000mm x H760mm x D490mm)', 218.68, 1000, 760, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '402BDRW', '540mm high x 490mm deep + 2 x 215mm drawers 400mm wide', '540mm high x 490mm deep + 2 x 215mm drawers 400mm wide (W400mm x H540mm x D490mm)', 154.32999999999998, 400, 540, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '502BDRW', '540mm high x 490mm deep + 2 x 215mm drawers 500mm wide', '540mm high x 490mm deep + 2 x 215mm drawers 500mm wide (W500mm x H540mm x D490mm)', 161.22999999999996, 500, 540, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '602BDRW', '540mm high x 490mm deep + 2 x 215mm drawers 600mm wide', '540mm high x 490mm deep + 2 x 215mm drawers 600mm wide (W600mm x H540mm x D490mm)', 164.45, 600, 540, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '802BDRW', '540mm high x 490mm deep + 2 x 215mm drawers 800mm wide', '540mm high x 490mm deep + 2 x 215mm drawers 800mm wide (W800mm x H540mm x D490mm)', 177.1, 800, 540, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '1002BDRW', '540mm high x 490mm deep + 2 x 215mm drawers 1000mm wide', '540mm high x 490mm deep + 2 x 215mm drawers 1000mm wide (W1000mm x H540mm x D490mm)', 182.16, 1000, 540, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '405BDRW', '1000mm high x 490mm deep + 5 x 175mm drawers 400mm wide', '1000mm high x 490mm deep + 5 x 175mm drawers 400mm wide (W400mm x H1000mm x D490mm)', 209.98999999999998, 400, 1000, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '505BDRW', '1000mm high x 490mm deep + 5 x 175mm drawers 500mm wide', '1000mm high x 490mm deep + 5 x 175mm drawers 500mm wide (W500mm x H1000mm x D490mm)', 215.04999999999998, 500, 1000, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '605BDRW', '1000mm high x 490mm deep + 5 x 175mm drawers 600mm wide', '1000mm high x 490mm deep + 5 x 175mm drawers 600mm wide (W600mm x H1000mm x D490mm)', 217.57999999999998, 600, 1000, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '805BDRW', '1000mm high x 490mm deep + 5 x 175mm drawers 800mm wide', '1000mm high x 490mm deep + 5 x 175mm drawers 800mm wide (W800mm x H1000mm x D490mm)', 227.23999999999998, 800, 1000, 490, 'Chest of drawers', TRUE, TRUE),
    ('bedroom', '1005BDRW', '1000mm high x 490mm deep + 5 x 175mm drawers 1000mm wide', '1000mm high x 490mm deep + 5 x 175mm drawers 1000mm wide (W1000mm x H1000mm x D490mm)', 229.99999999999997, 1000, 1000, 490, 'Chest of drawers', TRUE, TRUE)

ON CONFLICT (category, item_code) DO UPDATE SET
    item_name = EXCLUDED.item_name,
    description = EXCLUDED.description,
    base_price = EXCLUDED.base_price,
    width = EXCLUDED.width,
    height = EXCLUDED.height,
    depth = EXCLUDED.depth,
    subcategory = EXCLUDED.subcategory,
    dimension_based = EXCLUDED.dimension_based,
    updated_at = CURRENT_TIMESTAMP;


-- ============================================================================
-- VERIFICATION QUERY
-- ============================================================================

-- Check imported items
SELECT category, item_code, item_name, base_price, width, height, depth
FROM price_list_items
WHERE category = 'bedroom'
ORDER BY item_code
LIMIT 20;

-- Count total items
SELECT category, COUNT(*) as total_items, SUM(base_price) as total_value
FROM price_list_items
WHERE category = 'bedroom'
GROUP BY category;