CREATE TABLE garments (
    id text PRIMARY KEY,
    tags jsonb,
    pattern_spec jsonb,
    slot text,
    category text,
    size_norm text,
    brand text,
    usable_3d bool,
    best_photo_id bigint,
    created_at timestamptz NOT NULL DEFAULT now(),
    tagged_at timestamptz
);

ALTER TABLE items RENAME TO listings;
ALTER TABLE listings RENAME CONSTRAINT items_pkey TO listings_pkey;
ALTER TABLE listings RENAME CONSTRAINT items_source_source_id_key TO listings_source_source_id_key;
ALTER TABLE listings RENAME CONSTRAINT items_status_check TO listings_status_check;
ALTER INDEX items_active_slot_price RENAME TO listings_active_slot_price;
ALTER INDEX items_title_trgm RENAME TO listings_title_trgm;
ALTER INDEX items_untagged RENAME TO listings_untagged;
ALTER TABLE listings
    ADD COLUMN garment_id text REFERENCES garments ON DELETE SET NULL,
    ADD COLUMN link_reason text,
    ADD COLUMN link_score real,
    ADD COLUMN seller text,
    ADD COLUMN brand_raw text,
    ADD COLUMN stated_condition text,
    ADD COLUMN assessed_condition text,
    ADD COLUMN stock_photo bool NOT NULL DEFAULT false;
CREATE INDEX listings_garment_active ON listings (garment_id) WHERE status = 'active';

CREATE TABLE photos (
    id bigserial PRIMARY KEY,
    listing_id text NOT NULL REFERENCES listings ON DELETE CASCADE,
    idx smallint NOT NULL,
    path text NOT NULL,
    width int,
    height int,
    phash bigint NOT NULL,
    b0 smallint NOT NULL,
    b1 smallint NOT NULL,
    b2 smallint NOT NULL,
    b3 smallint NOT NULL,
    b4 smallint NOT NULL,
    b5 smallint NOT NULL,
    b6 smallint NOT NULL,
    b7 smallint NOT NULL,
    exif_rotated bool NOT NULL DEFAULT false,
    view text,
    rotation smallint NOT NULL DEFAULT 0 CHECK (rotation IN (0, 90, 180, 270)),
    state text,
    wrinkle text,
    UNIQUE (listing_id, idx)
);
CREATE INDEX photos_b0 ON photos (b0);
CREATE INDEX photos_b1 ON photos (b1);
CREATE INDEX photos_b2 ON photos (b2);
CREATE INDEX photos_b3 ON photos (b3);
CREATE INDEX photos_b4 ON photos (b4);
CREATE INDEX photos_b5 ON photos (b5);
CREATE INDEX photos_b6 ON photos (b6);
CREATE INDEX photos_b7 ON photos (b7);

ALTER TABLE garments ADD CONSTRAINT garments_best_photo_id_fkey FOREIGN KEY (best_photo_id) REFERENCES photos ON DELETE SET NULL;

CREATE TABLE garment_links_log (
    at timestamptz NOT NULL DEFAULT now(),
    listing_id text NOT NULL,
    from_garment text,
    to_garment text,
    reason text NOT NULL,
    score real
);

-- item_id stays the key until the backfill fills garment_id, then the backfill makes garment_id the primary key
ALTER TABLE assets ADD COLUMN garment_id text;
CREATE UNIQUE INDEX assets_garment_id_key ON assets (garment_id);
