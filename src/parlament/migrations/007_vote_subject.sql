-- Subject of a Chamber vote as shown on its nominal page ('Vot final - PL-x 449/2025 Adoptare ... privind ...').
-- The daily list often has only the vote type ('Vot final respingere'). '' means the page shows no subject.
ALTER TABLE votes ADD COLUMN subject text;

DROP INDEX votes_search_idx;
ALTER TABLE votes DROP COLUMN search;
ALTER TABLE votes ADD COLUMN search tsvector GENERATED ALWAYS AS (
    to_tsvector('simple', f_unaccent(coalesce(description, '') || ' ' || coalesce(subject, '')))
) STORED;
CREATE INDEX votes_search_idx ON votes USING gin (search);
