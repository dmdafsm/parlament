-- Senate votes, Senate bill pages and MP biographies.

-- Bills now come from both chambers: 'cd-<idp>' (cdep.ro) and 'senat-<cod>' (senat.ro).
ALTER TABLE bills ADD COLUMN chamber text NOT NULL DEFAULT 'cd' CHECK (chamber IN ('cd', 'senat'));

-- senat.ro prints the outcome of each vote ('Adoptat', 'Respins') and no time of day: `seq` keeps the published order.
ALTER TABLE votes ADD COLUMN result text;
ALTER TABLE votes ADD COLUMN seq integer;

-- Biography (CV) as published by the chamber: [{"section": ..., "entries": [{"label": ..., "text": ...}]}].
ALTER TABLE members ADD COLUMN cv jsonb;
ALTER TABLE members ADD COLUMN cv_url text;

-- Senate registry number as a key ('L511/2026'); cdep.ro sometimes prints it with the date ('L111/09.02.2026').
-- Matches Python's senat_bills.senate_key.
ALTER TABLE bills ADD COLUMN senate_key text GENERATED ALWAYS AS (
    CASE WHEN regexp_replace(upper(senate_number), '\s', '', 'g') ~ '^[LB]\d+/(\d{1,2}\.\d{1,2}\.)?\d{4}'
         THEN regexp_replace(regexp_replace(upper(senate_number), '\s', '', 'g'),
                             '^([LB])0*(\d+)/(?:\d{1,2}\.\d{1,2}\.)?(\d{4}).*$', '\1\2/\3') END
) STORED;
CREATE INDEX bills_senate_key_idx ON bills (senate_key);
