ALTER TABLE garments ADD COLUMN material text;
CREATE INDEX garments_slot_material ON garments (slot, material);
ALTER TABLE listings ADD COLUMN scrape_query text;
